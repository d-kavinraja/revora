"""kLLM managed-provider API.

Two surfaces:

* read-only dashboard data for any authenticated user (status, ready models,
  aggregate telemetry, the caller's own review activity);
* admin-only lifecycle actions (load a model, stop/rotate/pin a backend,
  set the always-on pool), every one audited and confirmation-gated.

The frontend never talks to kLLM. All kLLM traffic happens server-side inside
``app.services.kllm_service``, which normalizes responses into whitelisted
DTOs: no account names, API/gateway keys, Kaggle identity, tunnel/LAN URLs,
kernel references, raw prompts or scheduler internals ever leave this module.
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user
from app.db.session import get_db
from app.middleware.rate_limit import limiter
from app.models.execution import ReviewExecution
from app.models.github import Installation, PullRequest, Repository
from app.models.review import Review
from app.models.user import User
from app.services import kllm_service
from app.services.admin_audit import admin_audit
from app.services.kllm_service import KllmError

router = APIRouter()


# --- DTOs (whitelisted, explicit) ------------------------------------------


class KllmModelRead(BaseModel):
    key: str
    status: str
    loaded: bool
    ready: bool
    context_window: int | None = None
    vision: bool = False
    tags: list[str] = []
    backend_count: int = 0


class KllmBackendRead(BaseModel):
    id: str
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
    id: str
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
    can_manage: bool = False


class KllmGpuRead(BaseModel):
    index: int | None = None
    used_mib: int | None = None
    total_mib: int | None = None
    util: float | None = None
    temp: float | None = None


class KllmTelemetryBackendRead(BaseModel):
    id: str
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


class KllmLoadRequest(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    confirm: bool = False


class KllmConfirmRequest(BaseModel):
    confirm: bool = False


class KllmPinRequest(BaseModel):
    pinned: bool = True


class KllmKeepRequest(BaseModel):
    size: int = Field(ge=0, le=10)
    confirm: bool = False


class KllmActionResponse(BaseModel):
    status: str
    model: str | None = None
    models_affected: list[str] = []
    size: int | None = None


# --- helpers ---------------------------------------------------------------


def _is_admin(user: User) -> bool:
    return getattr(user, "role", "user") == "admin"


def _require_admin(user: User) -> None:
    """Backend-enforced admin check (never trusts the UI)."""
    if not _is_admin(user):
        raise HTTPException(
            status_code=403, detail="Administrator access required."
        )


def _require_enabled() -> None:
    if not settings.KLLM_ENABLED:
        raise HTTPException(
            status_code=503,
            detail=(
                "kLLM is disabled. Set KLLM_ENABLED=true in backend/.env and "
                "restart the backend to enable the managed provider."
            ),
        )


async def _snapshot_response(db: AsyncSession, user: User, force: bool) -> dict:
    snapshot = await kllm_service.get_snapshot(db, force=force)
    payload = snapshot.as_dict()
    payload["can_manage"] = _is_admin(user)
    return payload


# --- read-only dashboard ---------------------------------------------------


@router.get("/status", response_model=KllmStatusResponse)
async def get_status(
    refresh: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Live kLLM snapshot. Returns ``enabled=false`` when the feature is off."""
    force = bool(refresh and _is_admin(current_user))
    return await _snapshot_response(db, current_user, force)


@router.get("/models", response_model=list[KllmModelRead])
async def get_ready_models(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Only loaded-and-ready models; used by the repository model selector."""
    _require_enabled()
    models = await kllm_service.get_ready_models(db)
    return [m.as_dict() for m in models]


@router.get("/telemetry", response_model=KllmTelemetryResponse)
async def get_telemetry(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Aggregate GPU/session telemetry. No account names or backend URLs."""
    _require_enabled()
    try:
        return await kllm_service.get_telemetry(db)
    except KllmError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/activity", response_model=KllmActivityResponse)
async def get_activity(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The caller's own kLLM review executions (never kLLM's raw request log)."""
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


# --- admin lifecycle -------------------------------------------------------


async def _audit_failure(
    db: AsyncSession,
    request: Request,
    current_user: User,
    *,
    action: str,
    entity_id: str,
    exc: Exception,
) -> None:
    await admin_audit(
        db,
        action=action,
        entity_type="kllm",
        entity_id=entity_id,
        outcome="failure",
        details={"error": str(exc)[:300]},
        actor_id=str(current_user.id),
        actor_type="user_admin",
        request=request,
        commit=True,
    )


@router.post("/admin/refresh", response_model=KllmStatusResponse)
@limiter.limit("30/minute")
async def admin_refresh(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Force a real state fetch from kLLM (bypasses the 15 s cache)."""
    _require_admin(current_user)
    _require_enabled()
    kllm_service.invalidate_cache()
    return await _snapshot_response(db, current_user, True)


@router.post("/admin/models/load", response_model=KllmActionResponse)
@limiter.limit("10/minute")
async def admin_load_model(
    body: KllmLoadRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    _require_enabled()
    try:
        result = await kllm_service.load_model(db, body.model, confirm=body.confirm)
    except KllmError as exc:
        await _audit_failure(
            db,
            request,
            current_user,
            action="admin.kllm_model_load",
            entity_id=body.model,
            exc=exc,
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    await admin_audit(
        db,
        action="admin.kllm_model_load",
        entity_type="kllm",
        entity_id=body.model,
        details={"model": result.get("model"), "status": result.get("status")},
        actor_id=str(current_user.id),
        actor_type="user_admin",
        request=request,
        commit=True,
    )
    return result


@router.post("/admin/backends/{backend_id}/stop", response_model=KllmActionResponse)
@limiter.limit("10/minute")
async def admin_stop_backend(
    backend_id: str,
    body: KllmConfirmRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stop one backend. This stops every model/session served by it."""
    _require_admin(current_user)
    _require_enabled()
    try:
        result = await kllm_service.stop_backend(
            db, backend_id, confirm=body.confirm
        )
    except KllmError as exc:
        await _audit_failure(
            db,
            request,
            current_user,
            action="admin.kllm_backend_stop",
            entity_id=backend_id,
            exc=exc,
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    await admin_audit(
        db,
        action="admin.kllm_backend_stop",
        entity_type="kllm_backend",
        entity_id=backend_id,
        details={
            "status": result.get("status"),
            "models_affected": result.get("models_affected", []),
        },
        actor_id=str(current_user.id),
        actor_type="user_admin",
        request=request,
        commit=True,
    )
    return result


@router.post("/admin/backends/{backend_id}/rotate", response_model=KllmActionResponse)
@limiter.limit("10/minute")
async def admin_rotate_backend(
    backend_id: str,
    body: KllmConfirmRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    _require_enabled()
    try:
        result = await kllm_service.rotate_backend(
            db, backend_id, confirm=body.confirm
        )
    except KllmError as exc:
        await _audit_failure(
            db,
            request,
            current_user,
            action="admin.kllm_backend_rotate",
            entity_id=backend_id,
            exc=exc,
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    await admin_audit(
        db,
        action="admin.kllm_backend_rotate",
        entity_type="kllm_backend",
        entity_id=backend_id,
        details={"status": result.get("status"), "model": result.get("model")},
        actor_id=str(current_user.id),
        actor_type="user_admin",
        request=request,
        commit=True,
    )
    return result


@router.post("/admin/backends/{backend_id}/pin", response_model=KllmActionResponse)
@limiter.limit("30/minute")
async def admin_pin_backend(
    backend_id: str,
    body: KllmPinRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    _require_enabled()
    try:
        result = await kllm_service.pin_backend(db, backend_id, pinned=body.pinned)
    except KllmError as exc:
        await _audit_failure(
            db,
            request,
            current_user,
            action="admin.kllm_backend_pin",
            entity_id=backend_id,
            exc=exc,
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    await admin_audit(
        db,
        action="admin.kllm_backend_pin",
        entity_type="kllm_backend",
        entity_id=backend_id,
        details={"pinned": body.pinned, "status": result.get("status")},
        actor_id=str(current_user.id),
        actor_type="user_admin",
        request=request,
        commit=True,
    )
    return result


@router.post("/admin/keep", response_model=KllmActionResponse)
@limiter.limit("10/minute")
async def admin_set_keep(
    body: KllmKeepRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set the always-on pool size (quota impact; confirmation required > 0)."""
    _require_admin(current_user)
    _require_enabled()
    try:
        result = await kllm_service.set_keep(db, body.size, confirm=body.confirm)
    except KllmError as exc:
        await _audit_failure(
            db,
            request,
            current_user,
            action="admin.kllm_keep",
            entity_id="always_on",
            exc=exc,
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    await admin_audit(
        db,
        action="admin.kllm_keep",
        entity_type="kllm",
        entity_id="always_on",
        details={"size": body.size, "status": result.get("status")},
        actor_id=str(current_user.id),
        actor_type="user_admin",
        request=request,
        commit=True,
    )
    return result
