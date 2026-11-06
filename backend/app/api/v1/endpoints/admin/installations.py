"""Admin installation read endpoint (`GET /api/v1/admin/installations`)."""

from fastapi import APIRouter, Depends, Query

from app.core.deps_admin import get_current_admin
from app.db.session import get_db
from app.models.admin import AdminUser
from app.schemas.admin import AdminInstallationListResponse
from app.services import admin_stats

router = APIRouter()


@router.get("/installations", response_model=AdminInstallationListResponse)
async def admin_list_installations(
    status: str | None = Query(None, max_length=40),
    q: str | None = Query(None, max_length=255),
    app_id: int | None = Query(None),
    limit: int = Query(admin_stats.DEFAULT_PAGE),
    offset: int = Query(0),
    _admin: AdminUser = Depends(get_current_admin),
    db=Depends(get_db),
):
    try:
        return await admin_stats.list_installations(
            db,
            status=status,
            q=q,
            app_id=app_id,
            limit=limit,
            offset=offset,
        )
    except admin_stats.InvalidQuery as exc:
        from app.api.v1.endpoints.admin.common import http_400

        raise http_400(exc) from exc
