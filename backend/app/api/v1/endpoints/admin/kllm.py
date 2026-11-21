"""Admin-only kLLM lifecycle control (isolated admin namespace).

Mounted at ``/api/v1/admin/kllm``. Every handler depends on
``get_current_admin``, so the ordinary user namespace (``/api/v1/kllm``) can
never reach a lifecycle mutation. The frontend admin console is the only
consumer; kLLM itself stays server-side and its account names, keys, URLs and
scheduler internals never appear in a response.

Actions are explicit and audited. Model unload composes kLLM's per-account
backend stop because `/chat-ui/models/unload` is a no-op upstream. Any
in-flight work refuses an unload by default; ``force=true`` is required to
stop serving backends and is never retried after an ambiguous response.
"""

from contextlib import AsyncExitStack
from typing import Any

# NOTE: this module deliberately does NOT use `from __future__ import
# annotations`. The rate-limit decorator wraps the endpoint in a slowapi
# closure whose `__globals__` are slowapi's, so postponed annotations could
# not be resolved and FastAPI would treat request bodies as query params.
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.kllm import (
    KllmBackendRead,
    KllmPendingRead,
    KllmStatusResponse,
)
from app.core.deps_admin import get_current_admin
from app.db.session import get_db
from app.middleware.rate_limit import limiter
from app.models.admin import AdminUser
from app.services import kllm_autoload, kllm_service, user_presence
from app.services.admin_audit import admin_audit
from app.services.kllm_service import KllmError, canonical_model

router = APIRouter()


# --- DTOs ------------------------------------------------------------------


class AdminKllmBackendRead(KllmBackendRead):
    """Admin-only opaque control handle for one kLLM backend."""

    id: str


class AdminKllmPendingRead(KllmPendingRead):
    """Admin-only opaque control handle for one pending launch."""

    id: str


class KllmManualUnloadBlockRead(BaseModel):
    model: str
    blocked_at: str
    blocked_by: str
    reason: str


class AdminKllmStatusResponse(KllmStatusResponse):
    """Live kLLM projection plus persisted admin controls."""

    autoload: dict[str, Any]
    backends: list[AdminKllmBackendRead]
    pending: list[AdminKllmPendingRead]
    manual_unload_blocks: list[KllmManualUnloadBlockRead] = Field(default_factory=list)
    active_sessions: int = 0
    always_on_size: int | None = None
    always_on_desired_pool: int | None = None
    always_on_min_backends: int | None = None
    always_on_verified: bool = False
    default_model: str | None = None


class KllmLoadRequest(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    confirm: bool = False


class KllmUnloadRequest(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    confirm: bool = False
    force: bool = False
    disable_always_on: bool = False


class KllmConfirmRequest(BaseModel):
    confirm: bool = False
    force: bool = False


class KllmPinRequest(BaseModel):
    pinned: bool = True


class KllmAllowAutoloadRequest(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    confirm: bool = False


class KllmKeepRequest(BaseModel):
    size: int = Field(ge=0, le=10)
    confirm: bool = False


class KllmActionResult(BaseModel):
    status: str
    model: str | None = None
    automatic_loading_blocked: bool = False
    always_on_disabled: bool = False
    manual_block_cleared: bool = False
    models_affected: list[str] = []
    size: int | None = None
    desired_pool_size: int | None = None
    effective_min_backends: int | None = None
    effective_size: int | None = None
    effectively_disabled: bool | None = None
    verified: bool = False
    stopped: int | None = None
    pending_stopped: int | None = None
    targets: int | None = None
    remaining_backends: int | None = None
    remaining_pending: int | None = None
    sessions_affected: int | None = None
    inflight_affected: int | None = None
    errors: int | None = None


class KllmAutoloadGroup(BaseModel):
    enabled: bool = False
    allowed_models: list[str] = []


class KllmAutoloadPolicyRead(BaseModel):
    review_autoload: KllmAutoloadGroup
    login_preload: KllmAutoloadGroup
    active_session_autoload: KllmAutoloadGroup
    load_timeout_seconds: int
    max_concurrent_loads: int
    login_preload_cooldown_seconds: int
    changed_at: str | None = None
    changed_by: str | None = None
    version: int = 0


class KllmAutoloadPolicyUpdate(BaseModel):
    review_autoload: KllmAutoloadGroup | None = None
    login_preload: KllmAutoloadGroup | None = None
    active_session_autoload: KllmAutoloadGroup | None = None
    load_timeout_seconds: int | None = Field(default=None, ge=30, le=3600)
    max_concurrent_loads: int | None = Field(default=None, ge=1, le=5)
    login_preload_cooldown_seconds: int | None = Field(
        default=None, ge=0, le=86_400
    )
    version: int | None = Field(default=None, ge=0)


# --- helpers ---------------------------------------------------------------


async def _status_payload(
    db: AsyncSession, *, force: bool
) -> dict[str, Any]:
    snapshot = await kllm_service.get_snapshot(db, force=force)
    payload = snapshot.as_dict()
    payload["autoload"] = await kllm_autoload.get_policy(db, force=True)
    blocks = await kllm_autoload.get_manual_blocks(db, force=True)
    payload["manual_unload_blocks"] = kllm_autoload.manual_block_payload(
        {
            key: value
            for key, value in blocks.items()
            if key != "__unverifiable__" and value.get("model") == key
        }
    )
    payload["active_sessions"] = await user_presence.count_active_sessions(db)
    payload["default_model"] = await kllm_service.get_default_model(db)
    payload["always_on_size"] = None
    payload["always_on_desired_pool"] = None
    payload["always_on_min_backends"] = None
    payload["always_on_verified"] = False
    if snapshot.enabled and snapshot.reachable:
        try:
            config = await kllm_service.get_autoscale_config()
            verified = bool(config.get("verified"))
            payload["always_on_verified"] = verified
            if verified:
                payload["always_on_size"] = config.get("size")
                payload["always_on_desired_pool"] = config.get("desired_pool")
                payload["always_on_min_backends"] = config.get(
                    "autoscale_min_backends"
                )
        except KllmError:
            # The main snapshot already reports reachability; never fail the
            # whole admin status because the autoscale sub-endpoint is stale.
            pass
    return payload


def _error_detail(exc: KllmError) -> dict[str, str]:
    """Structured, safe error detail for admin lifecycle conflicts."""
    return {
        "message": exc.message,
        "code": exc.reason_code or exc.code,
    }


async def _audit_failure(
    db: AsyncSession,
    request: Request,
    current_admin: AdminUser,
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
        details={
            "error": type(exc).__name__,
            "status_code": getattr(exc, "status_code", None),
        },
        admin=current_admin,
        request=request,
        commit=True,
    )


async def _validate_allowed_models(
    db: AsyncSession, models: list[str] | None
) -> list[str] | None:
    """Canonicalize and verify administrator-approved model keys.

    Approval is only meaningful for models kLLM actually advertises, so the
    list is checked against a forced, fresh catalogue read. An empty list is
    always valid. Duplicates collapse to one canonical key.
    """
    if models is None:
        return None
    canonical: list[str] = []
    seen: set[str] = set()
    for value in models:
        key = canonical_model(str(value))
        if not key:
            raise HTTPException(
                status_code=422, detail="Approved models must be non-empty names."
            )
        if key not in seen:
            seen.add(key)
            canonical.append(key)

    if not canonical:
        return []

    snapshot = await kllm_service.get_snapshot(db, force=True)
    if not snapshot.enabled:
        raise HTTPException(
            status_code=503,
            detail=(
                "kLLM must be enabled and reachable to validate approved "
                "models."
            ),
        )
    if not snapshot.reachable:
        raise HTTPException(
            status_code=503,
            detail=(
                snapshot.error
                or "kLLM is unreachable; approved models cannot be validated."
            ),
        )
    if snapshot.stale:
        raise HTTPException(
            status_code=503,
            detail=(
                "kLLM state is stale; approved models cannot be validated right now."
            ),
        )
    catalogue = {model.key for model in snapshot.models}
    unknown = [key for key in canonical if key not in catalogue]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=(
                "Not in kLLM's model catalogue: "
                + ", ".join(unknown[:5])
                + ("…" if len(unknown) > 5 else "")
            ),
        )
    return canonical


# --- reads -----------------------------------------------------------------


@router.get("", response_model=AdminKllmStatusResponse)
async def get_kllm_status(
    refresh: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Live kLLM state plus the automatic-loading policy (admin only)."""
    del current_admin
    return await _status_payload(db, force=bool(refresh))


@router.post("/refresh", response_model=AdminKllmStatusResponse)
@limiter.limit("30/minute")
async def refresh_kllm_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Force a real kLLM state read (bypasses the 15 s cache)."""
    del request, current_admin
    kllm_service.invalidate_cache()
    return await _status_payload(db, force=True)


# --- lifecycle mutations ---------------------------------------------------


@router.post("/models/load", response_model=KllmActionResult)
@limiter.limit("10/minute")
async def load_model(
    body: KllmLoadRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    try:
        result = await kllm_autoload.manual_load_model(
            db, body.model, confirm=body.confirm, admin_id=current_admin.id
        )
    except KllmError as exc:
        await _audit_failure(
            db,
            request,
            current_admin,
            action="admin.kllm_model_load",
            entity_id=body.model,
            exc=exc,
        )
        raise HTTPException(
            status_code=exc.status_code, detail=_error_detail(exc)
        ) from exc

    await admin_audit(
        db,
        action="admin.kllm_model_load",
        entity_type="kllm",
        entity_id=body.model,
        details={"model": result.get("model"), "status": result.get("status")},
        admin=current_admin,
        request=request,
        commit=True,
    )
    return result


@router.post("/models/unload", response_model=KllmActionResult)
@limiter.limit("10/minute")
async def unload_model(
    body: KllmUnloadRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Stop every backend and pending launch serving one exact model."""
    try:
        result = await kllm_autoload.manual_unload_model(
            db,
            body.model,
            confirm=body.confirm,
            force=body.force,
            admin_id=current_admin.id,
            disable_always_on=body.disable_always_on,
        )
    except KllmError as exc:
        await _audit_failure(
            db,
            request,
            current_admin,
            action="admin.kllm_model_unload",
            entity_id=body.model,
            exc=exc,
        )
        raise HTTPException(
            status_code=exc.status_code, detail=_error_detail(exc)
        ) from exc

    await admin_audit(
        db,
        action="admin.kllm_model_unload",
        entity_type="kllm",
        entity_id=str(result.get("model") or body.model),
        details={
            "status": result.get("status"),
            "force": body.force,
            "automatic_loading_blocked": result.get("automatic_loading_blocked"),
            "always_on_disabled": result.get("always_on_disabled"),
            "stopped": result.get("stopped"),
            "targets": result.get("targets"),
            "remaining_backends": result.get("remaining_backends"),
            "remaining_pending": result.get("remaining_pending"),
            "errors": result.get("errors"),
        },
        admin=current_admin,
        request=request,
        commit=True,
    )
    return result


@router.post("/backends/{backend_id}/stop", response_model=KllmActionResult)
@limiter.limit("10/minute")
async def stop_backend(
    backend_id: str,
    body: KllmConfirmRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Stop one backend (and therefore every model/session it serves)."""
    try:
        result = await kllm_service.stop_backend(
            db, backend_id, confirm=body.confirm, force=body.force
        )
    except KllmError as exc:
        await _audit_failure(
            db,
            request,
            current_admin,
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
            "force": body.force,
            "models_affected": result.get("models_affected", []),
        },
        admin=current_admin,
        request=request,
        commit=True,
    )
    return result


@router.post("/backends/{backend_id}/rotate", response_model=KllmActionResult)
@limiter.limit("10/minute")
async def rotate_backend(
    backend_id: str,
    body: KllmConfirmRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    try:
        result = await kllm_service.rotate_backend(
            db, backend_id, confirm=body.confirm
        )
    except KllmError as exc:
        await _audit_failure(
            db,
            request,
            current_admin,
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
        admin=current_admin,
        request=request,
        commit=True,
    )
    return result


@router.post("/backends/{backend_id}/pin", response_model=KllmActionResult)
@limiter.limit("30/minute")
async def pin_backend(
    backend_id: str,
    body: KllmPinRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    try:
        result = await kllm_service.pin_backend(db, backend_id, pinned=body.pinned)
    except KllmError as exc:
        await _audit_failure(
            db,
            request,
            current_admin,
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
        admin=current_admin,
        request=request,
        commit=True,
    )
    return result


@router.post("/keep", response_model=KllmActionResult)
@limiter.limit("10/minute")
async def set_keep(
    body: KllmKeepRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Set the always-on pool size (quota impact; confirmation above zero)."""
    try:
        result = await kllm_service.set_keep(db, body.size, confirm=body.confirm)
    except KllmError as exc:
        await _audit_failure(
            db,
            request,
            current_admin,
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
        admin=current_admin,
        request=request,
        commit=True,
    )
    return result


# --- manual-unload precedence ---------------------------------------------


@router.post("/models/allow-autoload", response_model=KllmActionResult)
@limiter.limit("30/minute")
async def allow_autoload_after_manual_unload(
    body: KllmAllowAutoloadRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Clear a durable manual-unload block without issuing a model load."""
    canonical = canonical_model(body.model)
    if not canonical:
        raise HTTPException(status_code=422, detail="A model is required.")
    if not body.confirm:
        raise HTTPException(
            status_code=409,
            detail={"message": "Explicit confirmation is required.", "code": "confirmation_required"},
        )
    cleared = await kllm_autoload.clear_manual_block_for_admin(
        db, canonical, admin_id=current_admin.id
    )
    await admin_audit(
        db,
        action="admin.kllm_autoload_unblocked",
        entity_type="kllm",
        entity_id=canonical,
        details={"cleared": cleared, "model": canonical},
        admin=current_admin,
        request=request,
        commit=True,
    )
    return {
        "status": "success" if cleared else "already_allowed",
        "model": canonical,
        "automatic_loading_blocked": False,
        "manual_block_cleared": bool(cleared),
    }


# --- automatic-loading policy ---------------------------------------------


@router.get("/autoload", response_model=KllmAutoloadPolicyRead)
async def get_autoload_policy(
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    del current_admin
    return await kllm_autoload.get_policy(db, force=True)


@router.put("/autoload", response_model=KllmAutoloadPolicyRead)
@limiter.limit("30/minute")
async def update_autoload_policy(
    body: KllmAutoloadPolicyUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    updates = body.model_dump(exclude_unset=True)
    expected_version = updates.pop("version", None)

    for group in ("review_autoload", "login_preload", "active_session_autoload"):
        stored = updates.get(group)
        if isinstance(stored, dict):
            allowed = await _validate_allowed_models(
                db, stored.get("allowed_models")
            )
            stored = dict(stored)
            if allowed is not None:
                stored["allowed_models"] = allowed
            updates[group] = stored

    # A limit change must quiesce all cross-process load slots so no old
    # generation can remain active after the new limit becomes authoritative.
    try:
        async with AsyncExitStack() as gate_stack:
            if updates.get("max_concurrent_loads") is not None:
                await gate_stack.enter_async_context(
                    kllm_autoload.hold_global_load_gate(db)
                )

            new_policy, prior, conflict = await kllm_autoload.update_policy(
                db,
                updates,
                admin_id=current_admin.id,
                expected_version=expected_version,
            )
            if conflict is not None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "The automatic-loading policy changed since it was "
                        "loaded. Reload and retry."
                    ),
                )

            await admin_audit(
                db,
                action="admin.kllm_autoload_updated",
                entity_type="platform_setting",
                entity_id=kllm_autoload.KLLM_AUTOLOAD_KEY,
                details={
                    "prior": {
                        "review_autoload": prior.get("review_autoload"),
                        "login_preload": prior.get("login_preload"),
                        "active_session_autoload": prior.get(
                            "active_session_autoload"
                        ),
                        "version": prior.get("version"),
                    },
                    "new": {
                        "review_autoload": new_policy.get("review_autoload"),
                        "login_preload": new_policy.get("login_preload"),
                        "active_session_autoload": new_policy.get(
                            "active_session_autoload"
                        ),
                        "version": new_policy.get("version"),
                    },
                },
                admin=current_admin,
                request=request,
                commit=False,
            )
            await db.commit()
    except KllmError as exc:
        raise HTTPException(
            status_code=exc.status_code, detail=_error_detail(exc)
        ) from exc
    return kllm_autoload.admin_policy_payload(new_policy)
