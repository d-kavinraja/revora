"""Admin usage analytics master switch (runtime control)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps_admin import get_current_admin
from app.db.session import get_db
from app.middleware.rate_limit import limiter
from app.models.admin import AdminUser
from app.schemas.admin import AdminUsageAnalyticsRead, AdminUsageAnalyticsUpdate
from app.services.admin_audit import admin_audit
from app.services.platform_settings import platform_settings_service

router = APIRouter()


@router.get("/usage-analytics", response_model=AdminUsageAnalyticsRead)
async def get_usage_analytics(
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    state = await platform_settings_service.get_usage_analytics(db, force=True)
    return AdminUsageAnalyticsRead(
        enabled=bool(state.get("enabled")),
        changed_by=state.get("changed_by"),
        changed_at=state.get("changed_at"),
        version=int(state.get("version") or 0),
    )


@router.put("/usage-analytics", response_model=AdminUsageAnalyticsRead)
@limiter.limit("30/minute")
async def update_usage_analytics(
    request: Request,
    data: AdminUsageAnalyticsUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    new_state, prior, conflict = await platform_settings_service.set_usage_analytics(
        db,
        enabled=data.enabled,
        admin_id=current_admin.id,
        expected_version=data.version,
    )
    if conflict is not None:
        raise HTTPException(
            status_code=409,
            detail="Usage analytics state changed since it was loaded. Reload and retry.",
        )
    await admin_audit(
        db,
        action=(
            "admin.usage_analytics_enabled"
            if data.enabled
            else "admin.usage_analytics_disabled"
        ),
        entity_type="platform_setting",
        entity_id="usage_analytics",
        admin=current_admin,
        request=request,
        details={
            "prior": bool(prior.get("enabled")),
            "new": bool(new_state.get("enabled")),
        },
        commit=False,
    )
    await db.commit()
    return AdminUsageAnalyticsRead(
        enabled=bool(new_state.get("enabled")),
        changed_by=new_state.get("changed_by"),
        changed_at=new_state.get("changed_at"),
        version=int(new_state.get("version") or 0),
    )
