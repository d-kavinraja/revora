"""Admin-only kLLM Cloud control (isolated admin namespace).

Mounted at ``/api/v1/admin/kllm-cloud``. Every handler depends on
``get_current_admin``. Discovery, approval and diagnostics are quota-free:
the only live calls are ``GET /v1/models`` and the explicit ``/health``
warm probe, both answered without inference. The relay URL, credentials,
account identities and backend residency never appear in a response.

Approval is deny-by-default and per model: approving keeps an ``available``
``model_overrides`` row (the row *is* the approval record), revoking deletes
it, and the Chat/Review surfaces are independent flags on that same row.
"""

# NOTE: no ``from __future__ import annotations`` here on purpose: the
# rate-limit decorator wraps the endpoint in a slowapi closure whose
# ``__globals__`` are slowapi's own, so postponed annotations would be treated
# query params instead of a request body.
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps_admin import get_current_admin
from app.db.session import get_db
from app.middleware.rate_limit import limiter
from app.models.admin import AdminUser
from app.services import kllm_cloud_service
from app.services.admin_audit import admin_audit
from app.services.kllm_cloud_service import KllmCloudError

router = APIRouter()


class CloudModelRead(BaseModel):
    model_id: str
    key: str
    display_name: str
    classification: str
    canonical: str | None = None
    family: str | None = None
    context_window: int | None = None
    vision: bool = False
    tags: list[str] = []
    description: str | None = None
    approved: bool = False
    disabled: bool = False
    chat_enabled: bool = True
    review_enabled: bool = True
    available: bool = True
    ready: bool = False
    reason_code: str = "unknown"


class CloudDiagnosticsResponse(BaseModel):
    provider: str
    name: str
    enabled: bool
    configured: bool
    credential_configured: bool
    reachable: bool
    stale: bool
    state: str
    reason: str
    error: str | None = None
    error_reason: str | None = None
    last_success_at: str | None = None
    catalog_age_seconds: float | None = None
    cache_ttl_seconds: float
    concurrency_limit: int
    queue_timeout_seconds: float
    counts: dict[str, int]
    overlay: dict[str, int]
    backend_warm: dict[str, Any]
    models: list[CloudModelRead]


class CloudModelUpdate(BaseModel):
    """Partial update; every field is optional but at least one is required."""

    approved: bool | None = None
    disabled: bool | None = None
    chat_enabled: bool | None = None
    review_enabled: bool | None = None
    message: str | None = Field(default=None, max_length=500)


class CloudActionResult(BaseModel):
    status: str
    model: CloudModelRead | None = None
    refreshed: bool | None = None
    throttled: bool | None = None
    advertised: int | None = None
    backend_warm: dict[str, Any] | None = None


def _model_or_404(diagnostics: dict[str, Any], model_id: str) -> dict[str, Any]:
    for row in diagnostics.get("models", []):
        if row.get("model_id") == model_id:
            return row
    raise HTTPException(status_code=404, detail="Model not found in the kLLM Cloud catalogue.")


def _raise_cloud_error(exc: KllmCloudError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.reason_code or exc.code, "message": exc.message},
    ) from exc


@router.get("", response_model=CloudDiagnosticsResponse)
async def get_cloud_diagnostics(
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Quota-free provider state, catalogue reconciliation and approval list."""
    return await kllm_cloud_service.diagnostics(db)


@router.post("/refresh", response_model=CloudActionResult)
@limiter.limit("10/minute")
async def refresh_cloud_catalog(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Re-read ``GET /v1/models`` (free) and reconcile the catalogue."""
    result = await kllm_cloud_service.refresh_catalog(db)
    if result.get("refreshed"):
        await admin_audit(
            db,
            action="admin.kllm_cloud_catalog_refreshed",
            entity_type="kllm_cloud_provider",
            entity_id=kllm_cloud_service.PROVIDER_SLUG,
            admin=current_admin,
            request=request,
            details={
                "advertised": str(result.get("advertised") or 0),
                "reachable": str(bool(result.get("reachable"))),
            },
            commit=False,
        )
        await db.commit()
    return CloudActionResult(
        status="refreshed" if result.get("refreshed") else "throttled",
        refreshed=bool(result.get("refreshed")),
        throttled=bool(result.get("throttled")),
        advertised=result.get("advertised"),
    )


@router.post("/warm-probe", response_model=CloudActionResult)
@limiter.limit("30/minute")
async def probe_cloud_backend(
    request: Request,
    current_admin: AdminUser = Depends(get_current_admin),
):
    """``GET /health``: is *some* backend warm? Never per-model, never liveness."""
    warm = await kllm_cloud_service.probe_backend_warm(force=True)
    return CloudActionResult(status="probed", backend_warm=warm)


@router.put("/models/{model_id}", response_model=CloudActionResult)
@limiter.limit("30/minute")
async def update_cloud_model(
    model_id: str,
    data: CloudModelUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Approve, revoke, disable or re-surface one canonical chat model (audited)."""
    if (
        data.approved is None
        and data.disabled is None
        and data.chat_enabled is None
        and data.review_enabled is None
    ):
        raise HTTPException(status_code=400, detail="No change requested.")
    # KEY-05: the path may carry an alias, a media id or garbage. Resolving it
    # inside the guard means a typed 400 is returned instead of a 500, and an
    # unknown id never reaches an audit row or the relay.
    resolved = model_id
    audit_action = "admin.kllm_cloud_model_updated"
    details: dict[str, str] = {}
    try:
        resolved = kllm_cloud_service.model_id_from_key(model_id) or model_id
        details["model_id"] = resolved
        if data.disabled is True:
            _row, action = await kllm_cloud_service.set_disabled(
                db, resolved, True, message=data.message
            )
            audit_action = "admin.kllm_cloud_model_disabled"
        elif data.disabled is False:
            _row, action = await kllm_cloud_service.set_disabled(
                db, resolved, False, message=data.message
            )
            audit_action = "admin.kllm_cloud_model_enabled"
        elif data.approved is not None:
            _row, action = await kllm_cloud_service.set_approval(
                db,
                resolved,
                bool(data.approved),
                chat_enabled=data.chat_enabled,
                review_enabled=data.review_enabled,
                message=data.message,
            )
            audit_action = (
                "admin.kllm_cloud_model_approved"
                if data.approved
                else "admin.kllm_cloud_model_revoked"
            )
        else:
            _row, action = await kllm_cloud_service.set_surfaces(
                db,
                resolved,
                chat_enabled=data.chat_enabled,
                review_enabled=data.review_enabled,
            )
            audit_action = "admin.kllm_cloud_model_surfaces_changed"
    except KllmCloudError as exc:
        _raise_cloud_error(exc)
    if action == "noop":
        # A message-only or same-value update changed no state: return the
        # current projection without a misleading mutation audit event.
        diagnostics = await kllm_cloud_service.diagnostics(db)
        return CloudActionResult(
            status="noop",
            model=_model_or_404(diagnostics, resolved),
        )
    if data.approved is not None:
        details["approved"] = str(bool(data.approved))
    if data.disabled is not None:
        details["disabled"] = str(bool(data.disabled))
    if data.chat_enabled is not None:
        details["chat_enabled"] = str(bool(data.chat_enabled))
    if data.review_enabled is not None:
        details["review_enabled"] = str(bool(data.review_enabled))
    await admin_audit(
        db,
        action=audit_action,
        entity_type="kllm_cloud_model",
        entity_id=f"{kllm_cloud_service.PROVIDER_SLUG}:{resolved}",
        admin=current_admin,
        request=request,
        details=details,
        commit=False,
    )
    await db.commit()
    diagnostics = await kllm_cloud_service.diagnostics(db)
    return CloudActionResult(
        status="updated",
        model=_model_or_404(diagnostics, resolved),
    )


@router.delete("/models/{model_id}", response_model=CloudActionResult)
@limiter.limit("30/minute")
async def revoke_cloud_model(
    model_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Revoke an approval (returns the model to pending; providers untouched)."""
    resolved = model_id
    try:
        resolved = kllm_cloud_service.model_id_from_key(model_id) or model_id
        _row, action = await kllm_cloud_service.set_approval(
            db, resolved, False
        )
    except KllmCloudError as exc:
        _raise_cloud_error(exc)
    if action != "noop":
        await admin_audit(
            db,
            action="admin.kllm_cloud_model_revoked",
            entity_type="kllm_cloud_model",
            entity_id=f"{kllm_cloud_service.PROVIDER_SLUG}:{resolved}",
            admin=current_admin,
            request=request,
            details={"model_id": resolved},
            commit=False,
        )
    await db.commit()
    diagnostics = await kllm_cloud_service.diagnostics(db)
    return CloudActionResult(
        status="revoked" if action != "noop" else "noop",
        model=_model_or_404(diagnostics, resolved),
    )
