"""Admin overview endpoint (`GET /api/v1/admin/overview`).

Read-only aggregate widgets (§7.1). All numbers come from the database;
unrecorded metrics are returned as ``available: false`` markers.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.admin.common import http_400
from app.core.deps_admin import get_current_admin
from app.db.session import get_db
from app.models.admin import AdminUser
from app.schemas.admin import OverviewResponse
from app.services import admin_stats

router = APIRouter()


@router.get("/overview", response_model=OverviewResponse)
async def admin_overview(
    period: str = Query(
        "7d", description="24h | 7d | 30d | custom (requires start/end)"
    ),
    start: str | None = Query(None, description="ISO-8601 (custom period)"),
    end: str | None = Query(None, description="ISO-8601 (custom period)"),
    _admin: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        period_key, start_dt, end_dt = admin_stats.resolve_period(
            period, start, end
        )
    except admin_stats.InvalidQuery as exc:
        raise http_400(exc) from exc
    return await admin_stats.overview(
        db, period_key=period_key, start=start_dt, end=end_dt
    )
