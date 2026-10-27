"""Admin per-model overrides (phase 6, §11.2 / §18).

`GET /admin/models/overrides` lists every override row; `PUT` upserts one
`{provider_slug, model_id, status, message}` (404 unknown provider, 400
invalid status). `status='available'` clears the override — the model is
restored with no user action. Enforcement is per-model only: the provider,
its other models and the Model Lab page stay untouched. All writes are
audited (`admin.model_override_set` / `admin.model_override_cleared`).
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps_admin import get_current_admin
from app.db.session import get_db
from app.middleware.rate_limit import limiter
from app.models.admin import AdminUser
from app.models.platform import MODEL_OVERRIDE_STATUSES
from app.schemas.admin import AdminModelOverrideRead, AdminModelOverrideUpdate
from app.services.admin_audit import admin_audit
from app.services.model_overrides import model_overrides_service
from app.services.provider_registry import provider_registry_service

router = APIRouter()


@router.get("/models/overrides", response_model=list[AdminModelOverrideRead])
async def list_model_overrides(
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """All per-model overrides (admin only)."""
    rows = await model_overrides_service.list_rows(db)
    return [
        AdminModelOverrideRead(
            provider_slug=row.provider_slug,
            model_id=row.model_id,
            status=row.status,
            message=row.message,
        )
        for row in rows
    ]


@router.put("/models/overrides", response_model=AdminModelOverrideRead)
@limiter.limit("30/minute")
async def update_model_override(
    request: Request,
    data: AdminModelOverrideUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Upsert or clear one per-model override (audited)."""
    if data.status not in MODEL_OVERRIDE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="Invalid status. Expected one of: "
            + ", ".join(MODEL_OVERRIDE_STATUSES)
            + ".",
        )
    provider = await provider_registry_service.get_by_identifier(
        db, data.provider_slug
    )
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found.")

    # Normalize to the registry slug so enforcement aliases stay consistent.
    provider_slug = provider.slug
    _, action = await model_overrides_service.apply(
        db,
        provider_slug=provider_slug,
        model_id=data.model_id,
        status=data.status,
        message=data.message,
    )

    if action in ("set", "cleared"):
        audit_action = (
            "admin.model_override_set"
            if action == "set"
            else "admin.model_override_cleared"
        )
        details: dict[str, str] = {
            "provider_slug": provider_slug,
            "model_id": data.model_id,
        }
        if action == "set":
            details["status"] = data.status
        await admin_audit(
            db,
            action=audit_action,
            entity_type="model_override",
            entity_id=f"{provider_slug}:{data.model_id}",
            admin=current_admin,
            request=request,
            details=details,
            commit=False,
        )
    await db.commit()
    return AdminModelOverrideRead(
        provider_slug=provider_slug,
        model_id=data.model_id,
        status=data.status,
        message=data.message,
    )
