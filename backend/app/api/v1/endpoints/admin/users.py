"""Admin user endpoints (`GET/POST /api/v1/admin/users*`).

Read: paginated list + detail (profile, repositories, credentials metadata
only, reviews, recent sanitized errors, audit events).

Mutations (phase 3, plan §8): disable (reason required, bumps
``token_version`` so every live session dies immediately), enable, and
revoke-sessions. No hard deletion exists in v1 (decision D4). Every
mutation writes an audit event.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.admin.common import http_400
from app.core.deps_admin import get_current_admin
from app.db.session import get_db
from app.middleware.rate_limit import limiter
from app.models.admin import AdminUser
from app.schemas.admin import (
    AdminRevokeSessionsResponse,
    AdminUserDetail,
    AdminUserDisableRequest,
    AdminUserListResponse,
    AdminUserStatusRead,
)
from app.services import admin_stats
from app.services.admin_audit import admin_audit

router = APIRouter()


async def _get_target_user(
    db: AsyncSession, user_id: uuid.UUID
):
    user = await admin_stats.get_user(db, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return user


@router.get("/users", response_model=AdminUserListResponse)
async def admin_list_users(
    q: str | None = Query(None, max_length=200),
    status_filter: str | None = Query(None, alias="status"),
    sort: str = Query("created"),
    limit: int = Query(admin_stats.DEFAULT_PAGE),
    offset: int = Query(0),
    _admin: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await admin_stats.list_users(
            db,
            q=q,
            status=status_filter,
            sort=sort,
            limit=limit,
            offset=offset,
        )
    except admin_stats.InvalidQuery as exc:
        raise http_400(exc) from exc


@router.get("/users/{user_id}", response_model=AdminUserDetail)
async def admin_user_detail(
    user_id: uuid.UUID,
    reviews_limit: int = Query(20),
    reviews_offset: int = Query(0),
    _admin: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        detail = await admin_stats.user_detail(
            db,
            user_id,
            reviews_limit=reviews_limit,
            reviews_offset=reviews_offset,
        )
    except admin_stats.InvalidQuery as exc:
        raise http_400(exc) from exc
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return detail


@router.post("/users/{user_id}/disable", response_model=AdminUserStatusRead)
@limiter.limit("30/minute")
async def admin_disable_user(
    request: Request,
    user_id: uuid.UUID,
    payload: AdminUserDisableRequest,
    admin: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_target_user(db, user_id)
    already_disabled = (user.status or "active") == "disabled"

    user.status = "disabled"
    if user.disabled_at is None:
        user.disabled_at = datetime.now(UTC)
    # Kill every live session immediately (existing revocation mechanism).
    user.token_version = int(user.token_version or 0) + 1
    db.add(user)
    await admin_audit(
        db,
        action="user.disable",
        entity_type="user",
        entity_id=str(user.id),
        admin=admin,
        request=request,
        details={
            "reason": payload.reason,
            "already_disabled": already_disabled,
        },
        commit=False,
    )
    result = AdminUserStatusRead(
        id=user.id, status=user.status, disabled_at=user.disabled_at
    )
    await db.commit()
    return result


@router.post("/users/{user_id}/enable", response_model=AdminUserStatusRead)
@limiter.limit("30/minute")
async def admin_enable_user(
    request: Request,
    user_id: uuid.UUID,
    admin: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_target_user(db, user_id)
    user.status = "active"
    user.disabled_at = None
    db.add(user)
    await admin_audit(
        db,
        action="user.enable",
        entity_type="user",
        entity_id=str(user.id),
        admin=admin,
        request=request,
        commit=False,
    )
    result = AdminUserStatusRead(
        id=user.id, status=user.status, disabled_at=user.disabled_at
    )
    await db.commit()
    return result


@router.post(
    "/users/{user_id}/revoke-sessions",
    response_model=AdminRevokeSessionsResponse,
)
@limiter.limit("30/minute")
async def admin_revoke_user_sessions(
    request: Request,
    user_id: uuid.UUID,
    admin: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_target_user(db, user_id)
    user.token_version = int(user.token_version or 0) + 1
    db.add(user)
    await admin_audit(
        db,
        action="user.revoke_sessions",
        entity_type="user",
        entity_id=str(user.id),
        admin=admin,
        request=request,
        commit=False,
    )
    await db.commit()
    return AdminRevokeSessionsResponse(revoked=True)
