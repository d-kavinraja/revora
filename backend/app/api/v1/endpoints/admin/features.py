"""Admin feature-flag controls (phase 6, §11.1 / §18).

`GET /admin/features` lists every canonical flag (missing DB rows are
synthesized as `enabled` — zero-state parity); `PUT /admin/features/{key}`
validates the key (404 unknown) and status (400 invalid), upserts the row
and writes an `admin.feature_flag_changed` audit row. Flag flips apply with
no redeploy and never delete stored data (§11.1). The admin namespace is
exempt from maintenance (§12.3), so flags stay operable during downtime.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps_admin import get_current_admin
from app.db.session import get_db
from app.middleware.rate_limit import limiter
from app.models.admin import AdminUser
from app.models.platform import FEATURE_FLAG_KEYS, FLAG_STATUSES
from app.schemas.admin import AdminFeatureFlagRead, AdminFeatureFlagUpdate
from app.services.admin_audit import admin_audit
from app.services.platform_settings import platform_settings_service

router = APIRouter()


@router.get("/features", response_model=list[AdminFeatureFlagRead])
async def list_feature_flags(
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Every canonical flag with its current status/message (admin only)."""
    flags = await platform_settings_service.get_flags(db, force=True)
    return [AdminFeatureFlagRead(key=key, **flags[key]) for key in FEATURE_FLAG_KEYS]


@router.put("/features/{key}", response_model=AdminFeatureFlagRead)
@limiter.limit("30/minute")
async def update_feature_flag(
    request: Request,
    key: str,
    data: AdminFeatureFlagUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Set one flag's status/message (audited; live immediately)."""
    if key not in FEATURE_FLAG_KEYS:
        raise HTTPException(status_code=404, detail="Unknown feature flag.")
    if data.status not in FLAG_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="Invalid status. Expected one of: " + ", ".join(FLAG_STATUSES) + ".",
        )

    new_state, prior = await platform_settings_service.set_flag(
        db,
        key,
        status=data.status,
        message=data.message,
        admin_id=current_admin.id,
    )
    await admin_audit(
        db,
        action="admin.feature_flag_changed",
        entity_type="feature_flag",
        entity_id=key,
        admin=current_admin,
        request=request,
        details={
            "key": key,
            "prior_status": prior.get("status"),
            "new_status": new_state.get("status"),
        },
        commit=False,
    )
    await db.commit()
    return AdminFeatureFlagRead(key=key, **new_state)
