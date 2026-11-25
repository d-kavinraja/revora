"""Admin-only controls for the Revora-managed hosted Ollama provider.

Mounted at ``/api/v1/admin/hosted-ollama``. Every handler depends on
``get_current_admin``. This namespace is isolated from kLLM: toggling hosted
selection, refreshing discovery or waking the machine never touches the kLLM
provider, its readiness or the review pathway.

The endpoint URL, bearer token, wake API key and machine identifier are
server-side only and are never returned. Actions are explicit and audited.
"""

from typing import Any

# NOTE: deliberately no `from __future__ import annotations` — the slowapi
# rate-limit decorator wraps handlers in a closure whose __globals__ are
# slowapi's, so postponed annotations would break request-body parsing.
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps_admin import get_current_admin
from app.db.session import get_db
from app.middleware.rate_limit import limiter
from app.models.admin import AdminUser
from app.services import hosted_monitor, hosted_ollama_service
from app.services.admin_audit import admin_audit

router = APIRouter()


class AdminHostedModelRead(BaseModel):
    key: str
    model: str
    installed: bool = True
    loaded: bool = False
    status: str
    ready: bool
    readiness: str
    reason_code: str
    context_window: int | None = None
    vision: bool = False
    tags: list[str] = []
    resident: bool = False
    digest: str | None = None
    admin_loadable: bool = False
    runtime_unknown: bool = False


class AdminHostedConcurrencyRead(BaseModel):
    max_concurrent_requests: int
    max_concurrent_requests_per_model: int
    queue_timeout_s: float
    inflight: int
    queued: int
    inflight_by_model: dict[str, int] = {}
    distributed: bool = False


class AdminHostedWakeRead(BaseModel):
    enabled: bool
    configured: bool
    waking: bool
    last_error: str | None = None


class AdminHostedStatusResponse(BaseModel):
    enabled: bool
    env_enabled: bool
    selection_enabled: bool
    configured: bool
    reachable: bool
    stale: bool
    generated_at: str
    age_seconds: float
    error: str | None = None
    version: str | None = None
    models: list[AdminHostedModelRead]
    concurrency: AdminHostedConcurrencyRead
    wake: AdminHostedWakeRead
    monitor: dict[str, Any] = Field(default_factory=dict)


class AdminHostedSelectionUpdate(BaseModel):
    enabled: bool


class HostedLoadRequest(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    confirm: bool = False


async def _status_payload(db: AsyncSession, *, force: bool = False) -> dict[str, Any]:
    snapshot = await hosted_ollama_service.get_snapshot(db, force=force)
    return {
        "enabled": snapshot.enabled,
        "env_enabled": bool(settings.REVORA_HOSTED_OLLAMA_ENABLED),
        "selection_enabled": snapshot.selection_enabled,
        "configured": snapshot.configured,
        "reachable": snapshot.reachable,
        "stale": snapshot.stale,
        "generated_at": snapshot.generated_at.isoformat(),
        "age_seconds": snapshot.age_seconds,
        "error": snapshot.error,
        "version": snapshot.version,
        "models": [m.as_dict() for m in snapshot.models],
        "concurrency": snapshot.concurrency,
        "wake": hosted_ollama_service.wake_status(),
        "monitor": await hosted_monitor.get_state(),
    }


@router.get("", response_model=AdminHostedStatusResponse)
async def get_hosted_status(
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Live hosted-provider status: connection, discovery, models, concurrency, wake."""
    return await _status_payload(db, force=True)


@router.put("/selection", response_model=AdminHostedStatusResponse)
@limiter.limit("30/minute")
async def update_hosted_selection(
    request: Request,
    data: AdminHostedSelectionUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Enable/disable hosted model selection (backend-enforced; kLLM unaffected)."""
    await hosted_ollama_service.set_selection(
        db, enabled=data.enabled, admin_id=current_admin.id
    )
    await admin_audit(
        db,
        action=(
            "admin.hosted_ollama_enabled"
            if data.enabled
            else "admin.hosted_ollama_disabled"
        ),
        entity_type="platform_setting",
        entity_id=hosted_ollama_service.SELECTION_KEY,
        admin=current_admin,
        request=request,
        details={"enabled": bool(data.enabled)},
        commit=False,
    )
    await db.commit()
    hosted_ollama_service.invalidate_cache()
    return await _status_payload(db, force=True)


@router.post("/refresh", response_model=AdminHostedStatusResponse)
@limiter.limit("30/minute")
async def refresh_hosted_catalog(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Force a fresh discovery of runtime-loaded models (never auto-loads)."""
    hosted_ollama_service.invalidate_cache()
    await admin_audit(
        db,
        action="admin.hosted_ollama_refreshed",
        entity_type="platform_setting",
        entity_id=hosted_ollama_service.SELECTION_KEY,
        admin=current_admin,
        request=request,
        commit=False,
    )
    await db.commit()
    return await _status_payload(db, force=True)


@router.post("/models/load")
@limiter.limit("5/minute")
async def load_hosted_model(
    request: Request,
    body: HostedLoadRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Explicit admin-only load of an installed hosted model.

    Never triggered by chat, catalog refresh, heartbeat or monitoring. A
    successful HTTP response is not proof of loading; ``verified`` is.
    """
    if not body.confirm:
        raise HTTPException(
            status_code=409,
            detail={"message": "Explicit confirmation is required.", "code": "confirmation_required"},
        )
    try:
        result = await hosted_ollama_service.load_model(db, body.model)
    except hosted_ollama_service.HostedError as exc:
        await admin_audit(
            db,
            action="admin.hosted_ollama_model_load",
            entity_type="hosted_ollama",
            entity_id=body.model,
            outcome="failure",
            details={"error": type(exc).__name__, "status_code": exc.status_code},
            admin=current_admin,
            request=request,
            commit=True,
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except Exception as exc:
        await admin_audit(
            db,
            action="admin.hosted_ollama_model_load",
            entity_type="hosted_ollama",
            entity_id=body.model,
            outcome="failure",
            details={"error": type(exc).__name__},
            admin=current_admin,
            request=request,
            commit=True,
        )
        raise HTTPException(status_code=500, detail="Hosted model load failed.") from exc

    await admin_audit(
        db,
        action="admin.hosted_ollama_model_load",
        entity_type="hosted_ollama",
        entity_id=body.model,
        details={"status": result.get("status"), "verified": bool(result.get("verified"))},
        admin=current_admin,
        request=request,
        commit=True,
    )
    return result


@router.post("/wake", response_model=AdminHostedStatusResponse)
@limiter.limit("6/minute")
async def wake_hosted_machine(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Explicitly wake the hosting machine and wait for the runtime to answer."""
    if not settings.REVORA_HOSTED_WAKE_ENABLED:
        raise HTTPException(
            status_code=409,
            detail="Hosted wake is disabled in the backend environment.",
        )
    ready = await hosted_ollama_service.wake_and_wait_ready()
    await admin_audit(
        db,
        action="admin.hosted_ollama_wake",
        entity_type="platform_setting",
        entity_id=hosted_ollama_service.SELECTION_KEY,
        admin=current_admin,
        request=request,
        details={"ready": bool(ready)},
        commit=False,
    )
    await db.commit()
    return await _status_payload(db, force=True)
