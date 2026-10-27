"""Admin repository read endpoint (`GET /api/v1/admin/repositories`).

Owner joins, installation status, configured mapping plus derived mapping
health (ok | stale | missing), review counts and recent failures (§7.3).
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.admin.common import http_400
from app.core.deps_admin import get_current_admin
from app.db.session import get_db
from app.models.admin import AdminUser
from app.schemas.admin import AdminRepositoryListResponse
from app.services import admin_stats

router = APIRouter()


@router.get("/repositories", response_model=AdminRepositoryListResponse)
async def admin_list_repositories(
    user: str | None = Query(None, max_length=255),
    provider: str | None = Query(None, max_length=50),
    mapping: str | None = Query(None, description="ok | stale | missing"),
    limit: int = Query(admin_stats.DEFAULT_PAGE),
    offset: int = Query(0),
    _admin: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await admin_stats.list_repositories(
            db,
            user=user,
            provider=provider,
            mapping=mapping,
            limit=limit,
            offset=offset,
        )
    except admin_stats.InvalidQuery as exc:
        raise http_400(exc) from exc
