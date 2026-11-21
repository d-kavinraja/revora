"""kLLM managed-provider read-only API for ordinary users.

This namespace exposes status, model readiness, aggregate telemetry and the
caller's own review activity. It deliberately contains **no** lifecycle
mutations: load/unload, backend stop/rotate/pin and the always-on pool are
admin-only and live under ``/api/v1/admin/kllm`` behind the separate admin
session.

The frontend never talks to kLLM. All kLLM traffic happens server-side inside
``app.services.kllm_service``, which normalizes responses into whitelisted
DTOs: no account names, API/gateway keys, Kaggle identity, tunnel/LAN URLs,
kernel references, raw prompts or scheduler internals ever leave this module.
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_session, get_current_user
from app.db.session import get_db
from app.models.execution import ReviewExecution
from app.models.github import Installation, PullRequest, Repository
from app.models.review import Review
from app.models.user import User
from app.services import kllm_autoload, kllm_service, user_presence
from app.services.kllm_service import KllmError

router = APIRouter()


# --- DTOs (whitelisted, explicit) ------------------------------------------


class KllmModelRead(BaseModel):
    key: str
    status: str
    loaded: bool
    ready: bool
    #: Backend-computed user-facing projection; never interpreted client-side.
    readiness: str = "unknown"
    reason_code: str = "unknown"
    context_window: int | None = None
    vision: bool = False
    tags: list[str] = []
    backend_count: int = 0


class KllmModelOptionRead(BaseModel):
    """A selectable model for repository configuration.

    ``loads_on_demand`` marks an administrator-approved model that is not
    currently loaded. The UI must present it as "loads on demand", never as
    ready.
    """

    model_name: str
    canonical_model_name: str
    provider: str
    readiness: str
    reason_code: str
    loads_on_demand: bool
    context_window: int | None = None
    supports_vision: bool = False
    status: str
    validation_timestamp: str


class KllmBackendRead(BaseModel):
    #: Always null on the ordinary-user surface. The admin namespace exposes
    #: the opaque control handle in its own response model.
    id: str | None = None
    model: str | None = None
    healthy: bool
    state: str
    up_s: int | None = None
    left_s: int | None = None
    draining: bool = False
    replaced_by: str | None = None
    sessions: int | None = None
    inflight: int | None = None
    idle_s: int | None = None
    errors_5m: int = 0
    pinned: bool = False
    rpm: float | None = None
    quota_used_h: float | None = None
    quota_limit_h: float | None = None
    gpu: dict[str, Any] | None = None


class KllmPendingRead(BaseModel):
    #: Always null on the ordinary-user surface.
    id: str | None = None
    model: str | None = None
    phase: str
    failed: bool = False
    age_s: int | None = None


class KllmClientRead(BaseModel):
    kind: str
    sessions: int = 0
    rpm: float | None = None


class KllmTrafficRead(BaseModel):
    rpm: float | None = None
    ttft_p50: float | None = None


class KllmRelayHealthRead(BaseModel):
    ok: bool = False
    inflight: int = 0


class KllmSummaryRead(BaseModel):
    backends: int = 0
    healthy_backends: int = 0
    running_backends: int = 0
    draining_backends: int = 0
    pinned_backends: int = 0
    sessions: int = 0
    inflight: int = 0
    loaded_models: int = 0
    ready_models: int = 0
    loading_models: int = 0
    failed_models: int = 0
    pending_backends: int = 0


class KllmStatusResponse(BaseModel):
    enabled: bool
    configured: bool
    reachable: bool
    stale: bool
    generated_at: datetime
    age_seconds: float
    error: str | None = None
    relay_health: KllmRelayHealthRead
    summary: KllmSummaryRead
    models: list[KllmModelRead]
    backends: list[KllmBackendRead]
    pending: list[KllmPendingRead]
    clients: list[KllmClientRead]
    traffic: KllmTrafficRead
    supervisor: bool = False
    autoscale: bool = False


class KllmGpuRead(BaseModel):
    index: int | None = None
    used_mib: int | None = None
    total_mib: int | None = None
    util: float | None = None
    temp: float | None = None


class KllmTelemetryBackendRead(BaseModel):
    #: Always null on the ordinary-user surface.
    id: str | None = None
    model: str | None = None
    gpu_used_mib: int | None = None
    gpu_total_mib: int | None = None
    gpu_util: float | None = None
    sessions: int = 0
    inflight: int = 0
    rpm: float | None = None


class KllmTelemetryTotalsRead(BaseModel):
    gpu_used_mib: int = 0
    gpu_total_mib: int = 0
    gpu_util: float | None = None
    backends: int = 0
    sessions: int = 0
    inflight: int = 0
    rpm: float = 0.0


class KllmTelemetryResponse(BaseModel):
    available: bool
    stale: bool
    generated_at: datetime
    age_seconds: float
    error: str | None = None
    reason: str | None = None
    gpus: list[KllmGpuRead]
    backends: list[KllmTelemetryBackendRead]
    totals: KllmTelemetryTotalsRead


class KllmActivityItem(BaseModel):
    id: str
    status: str
    model: str | None = None
    repository_full_name: str | None = None
    pr_number: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    total_tokens: int | None = None
    has_error: bool = False


class KllmActivityResponse(BaseModel):
    enabled: bool
    items: list[KllmActivityItem]


class KllmSessionHeartbeatRequest(BaseModel):
    client_session_id: str = Field(min_length=1, max_length=64)
    active: bool = True


class KllmSessionRead(BaseModel):
    active: bool
    last_seen_at: datetime | None = None
    expires_at: datetime | None = None


class KllmSessionReconciliationRead(BaseModel):
    model: str
    state: str
    reason_code: str
    status: str | None = None


class KllmSessionHeartbeatResponse(BaseModel):
    session: KllmSessionRead
    models: list[KllmSessionReconciliationRead] = []


# --- helpers ---------------------------------------------------------------


def _require_enabled() -> None:
    if not settings.KLLM_ENABLED:
        raise HTTPException(
            status_code=503,
            detail=kllm_service.DISABLED_MESSAGE,
        )


def _public_status_payload(snapshot: kllm_service.KllmSnapshot) -> dict[str, Any]:
    """Project kLLM state for ordinary users without control identifiers.

    kLLM account/backend handles are required only by the admin lifecycle
    routes. The user surface keeps aggregate/runtime telemetry but strips the
    opaque control handles and replacement identity entirely.
    """
    payload = snapshot.as_dict()
    payload["backends"] = [
        {
            **row,
            "id": None,
            "replaced_by": None,
        }
        for row in payload.get("backends", [])
    ]
    payload["pending"] = [
        {**row, "id": None}
        for row in payload.get("pending", [])
    ]
    return payload


def _public_telemetry_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip backend control handles from ordinary-user telemetry."""
    return {
        **payload,
        "backends": [
            {**row, "id": None}
            for row in payload.get("backends", [])
        ],
    }


# --- per-tab presence (advisory, never a lifecycle capability) --------------


@router.post("/session/heartbeat", response_model=KllmSessionHeartbeatResponse)
async def session_heartbeat(
    body: KllmSessionHeartbeatRequest,
    session: tuple[User, dict] = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
):
    """Refresh this browser tab's activity and best-effort reconcile kLLM.

    The caller is already authenticated by the same JWT whose ``jti`` is
    fingerprinted here. No raw token identity or lifecycle capability is
    returned to the browser.
    """
    current_user, payload = session
    try:
        row = await user_presence.upsert_heartbeat(
            db,
            user_id=current_user.id,
            payload=payload,
            client_session_id=body.client_session_id,
            active=body.active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await user_presence.prune_expired(db)
    await db.commit()
    status = user_presence.public_status(row)
    models = await kllm_autoload.reconcile_session_models(db)
    return {"session": status, "models": models}


@router.post("/session/end", response_model=KllmSessionRead)
async def session_end(
    body: KllmSessionHeartbeatRequest,
    session: tuple[User, dict] = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
):
    """Mark one browser tab inactive. Never unloads a kLLM model."""
    current_user, _payload = session
    try:
        row = await user_presence.deactivate(
            db,
            user_id=current_user.id,
            client_session_id=body.client_session_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return user_presence.public_status(row)


@router.get("/session", response_model=KllmSessionRead)
async def session_status(
    client_session_id: str = Query(min_length=1, max_length=64),
    session: tuple[User, dict] = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
):
    current_user, _payload = session
    try:
        return await user_presence.get_status(
            db,
            user_id=current_user.id,
            client_session_id=client_session_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --- read-only dashboard ---------------------------------------------------


@router.get("/status", response_model=KllmStatusResponse)
async def get_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Live kLLM snapshot. Returns ``enabled=false`` when the feature is off.

    Ordinary users never get a forced-refresh path; the 15 s cache is
    intentional. Administrators use the isolated admin namespace.
    """
    del current_user
    snapshot = await kllm_service.get_snapshot(db)
    return _public_status_payload(snapshot)


@router.get("/models", response_model=list[KllmModelRead])
async def get_ready_models(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Only loaded-and-ready models."""
    del current_user
    _require_enabled()
    models = await kllm_service.get_ready_models(db)
    return [m.as_dict() for m in models]


@router.get("/models/options", response_model=list[KllmModelOptionRead])
async def get_model_options(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Read-only model choices: ready models plus approved on-demand models.

    No lifecycle control is exposed here. An unloaded model appears only when
    an administrator explicitly approved it for review-demand loading, and is
    always flagged ``loads_on_demand``.
    """
    del current_user
    _require_enabled()
    return await kllm_service.get_model_options(db)


@router.get("/telemetry", response_model=KllmTelemetryResponse)
async def get_telemetry(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Aggregate GPU/session telemetry. No account names or backend URLs."""
    del current_user
    _require_enabled()
    try:
        telemetry = await kllm_service.get_telemetry(db)
        return _public_telemetry_payload(telemetry)
    except KllmError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/activity", response_model=KllmActivityResponse)
async def get_activity(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The caller's own kLLM review executions (never kLLM's request log)."""
    if not settings.KLLM_ENABLED:
        return {"enabled": False, "items": []}

    result = await db.execute(
        select(ReviewExecution)
        .join(Review, ReviewExecution.review_id == Review.id)
        .join(PullRequest, Review.pr_id == PullRequest.id)
        .join(Repository, PullRequest.repo_id == Repository.id)
        .join(Installation, Repository.installation_id == Installation.id)
        .where(Installation.user_id == current_user.id)
        .where(ReviewExecution.provider == kllm_service.KLLM_SLUG)
        .order_by(ReviewExecution.started_at.desc().nullslast())
        .limit(limit)
    )

    items: list[dict[str, Any]] = []
    for row in result.scalars().all():
        tokens = row.tokens if isinstance(row.tokens, dict) else {}
        total = tokens.get("total_tokens")
        if not isinstance(total, (int, float)):
            prompt = tokens.get("prompt_tokens")
            completion = tokens.get("completion_tokens")
            if isinstance(prompt, (int, float)) or isinstance(
                completion, (int, float)
            ):
                total = int(prompt or 0) + int(completion or 0)
            else:
                total = None
        items.append(
            {
                "id": str(row.id),
                "status": row.status,
                "model": row.model,
                "repository_full_name": row.repository_full_name,
                "pr_number": row.pr_number,
                "started_at": row.started_at,
                "completed_at": row.completed_at,
                "duration_ms": row.duration_ms,
                "total_tokens": int(total) if total is not None else None,
                "has_error": bool(row.error_message),
            }
        )
    return {"enabled": True, "items": items}
