"""Admin credential controls (phase 4, §10 / §18).

Metadata only — key material is never returned (not even masked) and
never decrypted. Disabling never deletes a row or touches
``encrypted_key``; re-enabling restores eligibility everywhere because all
selection helpers filter on ``api_keys.is_enabled`` (S7).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.admin.common import http_400
from app.core.deps_admin import get_current_admin
from app.db.session import get_db
from app.middleware.rate_limit import limiter
from app.models.admin import AdminUser
from app.models.api_key import ApiKey
from app.models.user import User
from app.schemas.admin import AdminKeyListResponse, AdminKeyRead
from app.services.admin_audit import admin_audit
from app.services.admin_stats import InvalidQuery, validate_pagination

router = APIRouter()


def _to_read(key: ApiKey, user_email: str) -> AdminKeyRead:
    return AdminKeyRead(
        id=key.id,
        user_id=key.user_id,
        user_email=user_email,
        provider=key.provider,
        label=key.label,
        is_valid=key.is_valid,
        is_enabled=key.is_enabled,
        last_used_at=key.last_used_at,
        created_at=key.created_at,
    )


def _filters(user_id: uuid.UUID | None, provider: str | None):
    clauses = []
    if user_id is not None:
        clauses.append(ApiKey.user_id == user_id)
    if provider:
        clauses.append(ApiKey.provider.ilike(provider))
    return clauses


@router.get("/keys", response_model=AdminKeyListResponse)
async def list_admin_keys(
    user_id: uuid.UUID | None = None,
    provider: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Credential metadata with label/status only (no key material)."""
    try:
        limit, offset = validate_pagination(limit, offset)
    except InvalidQuery as exc:
        raise http_400(exc)

    clauses = _filters(user_id, provider)

    total = (
        await db.execute(select(func.count(ApiKey.id)).where(*clauses))
    ).scalar() or 0

    result = await db.execute(
        select(ApiKey, User.email)
        .join(User, User.id == ApiKey.user_id)
        .where(*clauses)
        .order_by(ApiKey.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    items = [_to_read(key, email) for key, email in result.all()]
    return AdminKeyListResponse(items=items, total=total, limit=limit, offset=offset)


async def _set_key_enabled(
    db: AsyncSession,
    key_id: uuid.UUID,
    enabled: bool,
    request: Request,
    current_admin: AdminUser,
) -> AdminKeyRead:
    key = await db.get(ApiKey, key_id)
    if not key:
        raise HTTPException(status_code=404, detail="Credential not found")

    key.is_enabled = enabled
    db.add(key)

    await admin_audit(
        db,
        action="admin.credential_enabled" if enabled else "admin.credential_disabled",
        entity_type="api_key",
        entity_id=str(key.id),
        admin=current_admin,
        request=request,
        details={
            "provider": key.provider,
            "label": key.label,
            "user_id": str(key.user_id),
        },
        commit=False,
    )
    await db.commit()
    await db.refresh(key)

    email = (
        await db.execute(select(User.email).where(User.id == key.user_id))
    ).scalar() or ""
    return _to_read(key, email)


@router.post("/keys/{key_id}/disable", response_model=AdminKeyRead)
@limiter.limit("30/minute")
async def disable_admin_key(
    key_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Exclude a credential from every selection path (audited)."""
    return await _set_key_enabled(db, key_id, False, request, current_admin)


@router.post("/keys/{key_id}/enable", response_model=AdminKeyRead)
@limiter.limit("30/minute")
async def enable_admin_key(
    key_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Re-include a previously disabled credential (audited)."""
    return await _set_key_enabled(db, key_id, True, request, current_admin)
