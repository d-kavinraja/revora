"""Admin audit-log viewer (phase 7, §16 / §18).

`GET /admin/audit` exposes the full operational audit trail — admin
actions (actor, action, target, time, outcome, safe scalar details) and
existing user/system rows. Filters: exact `action`/`entity_type`, substring
`actor`, optional half-open `period` window (omitted = all history; there
is no auto-purge in v1). Pagination follows the shared `limit <= 100` rule.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.admin.common import http_400
from app.core.deps_admin import get_current_admin
from app.db.session import get_db
from app.models.admin import AdminUser
from app.schemas.admin import AdminAuditListResponse
from app.services.admin_stats import (
    DEFAULT_PAGE,
    InvalidQuery,
    list_audit,
    resolve_period,
    validate_pagination,
)

router = APIRouter()


@router.get("/audit", response_model=AdminAuditListResponse)
async def read_audit_log(
    action: str | None = Query(default=None, max_length=100),
    actor: str | None = Query(default=None, max_length=100),
    entity_type: str | None = Query(default=None, max_length=50),
    period: str | None = Query(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_PAGE),
    offset: int = Query(default=0),
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Filtered, paginated audit rows (newest first)."""
    window_start = None
    window_end = None
    try:
        if period is not None:
            _, window_start, window_end = resolve_period(period, start, end)
        elif start is not None or end is not None:
            raise InvalidQuery("start/end require period=custom")
        limit, offset = validate_pagination(limit, offset)
    except InvalidQuery as exc:
        raise http_400(exc)

    return await list_audit(
        db,
        action=action,
        actor=actor,
        entity_type=entity_type,
        start=window_start,
        end=window_end,
        limit=limit,
        offset=offset,
    )
