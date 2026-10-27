"""Admin maintenance controls (phase 5, §12.2 / §18).

`GET /admin/maintenance` returns the full internal state (incl. `reason`,
actor and version); `PUT /admin/maintenance` applies a whitelisted update
with optimistic-concurrency (`version` → 409) and audit rows. The admin
namespace is maintenance-exempt (§12.3), so this endpoint doubles as the
in-app recovery path (B25: disable → full traffic resumes with no redeploy).
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps_admin import get_current_admin
from app.db.session import get_db
from app.middleware.rate_limit import limiter
from app.models.admin import AdminUser
from app.schemas.admin import AdminMaintenanceRead, AdminMaintenanceUpdate
from app.services.admin_audit import admin_audit
from app.services.platform_settings import platform_settings_service, public_state

router = APIRouter()


@router.get("/maintenance", response_model=AdminMaintenanceRead)
async def get_maintenance_state(
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Current maintenance state (admin only; includes internal fields)."""
    state = await platform_settings_service.get_maintenance(db, force=True)
    return AdminMaintenanceRead(**state)


@router.put("/maintenance", response_model=AdminMaintenanceRead)
@limiter.limit("30/minute")
async def update_maintenance_state(
    request: Request,
    data: AdminMaintenanceUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Update maintenance mode (audited, optimistic concurrency)."""
    updates = data.model_dump(exclude_unset=True)
    expected_version = updates.pop("version", None)

    if not updates:
        state = await platform_settings_service.get_maintenance(db, force=True)
        return AdminMaintenanceRead(**state)

    if updates.get("enabled") is True:
        action = "admin.maintenance_enabled"
    elif updates.get("enabled") is False:
        action = "admin.maintenance_disabled"
    else:
        action = "admin.maintenance_message_updated"

    new_state, prior, conflict = await platform_settings_service.set_maintenance(
        db,
        updates,
        admin_id=current_admin.id,
        expected_version=expected_version,
    )
    if conflict is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Maintenance state changed since it was loaded. "
                "Reload and retry."
            ),
        )

    await admin_audit(
        db,
        action=action,
        entity_type="platform_setting",
        entity_id="maintenance",
        admin=current_admin,
        request=request,
        details={"prior": public_state(prior), "new": public_state(new_state)},
        commit=False,
    )
    await db.commit()
    return AdminMaintenanceRead(**new_state)
