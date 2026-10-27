"""Admin review read endpoint (`GET /api/v1/admin/reviews`).

Configured mapping (repository settings) side by side with the actual
latest execution provider/model — they differ after fallback (§15).
Unrecorded executions render ``null``, never fabricated values.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.admin.common import http_400
from app.core.deps_admin import get_current_admin
from app.db.session import get_db
from app.models.admin import AdminUser
from app.schemas.admin import AdminReviewListResponse
from app.services import admin_stats

router = APIRouter()


@router.get("/reviews", response_model=AdminReviewListResponse)
async def admin_list_reviews(
    user: str | None = Query(None, max_length=255),
    repo: str | None = Query(None, max_length=500),
    provider: str | None = Query(None, max_length=100),
    model: str | None = Query(None, max_length=200),
    status_filter: str | None = Query(None, alias="status", max_length=50),
    error: str | None = Query(None, max_length=200),
    period: str | None = Query(None, description="24h | 7d | 30d | custom"),
    start: str | None = Query(None),
    end: str | None = Query(None),
    limit: int = Query(admin_stats.DEFAULT_PAGE),
    offset: int = Query(0),
    _admin: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await admin_stats.list_reviews(
            db,
            user=user,
            repo=repo,
            provider=provider,
            model=model,
            status=status_filter,
            error=error,
            period=period,
            start=start,
            end=end,
            limit=limit,
            offset=offset,
        )
    except admin_stats.InvalidQuery as exc:
        raise http_400(exc) from exc
