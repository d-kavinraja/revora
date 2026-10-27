"""Admin authorization dependency for `/api/v1/admin/*`.

Completely isolated from user auth (`core/deps.py`): separate cookie
(`revora_admin_session`), separate identity table (`admin_users`), opaque
server-side session tokens stored as SHA-256 hashes. The user JWT is never
accepted here, and the admin cookie can never authenticate a user route.
"""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.admin import AdminSession, AdminUser

ADMIN_SESSION_COOKIE = "revora_admin_session"
ADMIN_SESSION_ABSOLUTE_HOURS = 8
ADMIN_SESSION_SLIDING_HOURS = 2
ADMIN_SESSION_MAX_HOURS = 24

_NOT_AUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
)


def hash_admin_token(raw_token: str) -> str:
    """SHA-256 hex digest of a raw admin session token (hash-only storage)."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _as_utc(dt: datetime) -> datetime:
    """SQLite returns naive datetimes; treat stored values as UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def admin_session_cookie_kwargs() -> dict[str, Any]:
    """Flags for the backend-written admin session cookie.

    Mirrors the proven user-cookie pattern in `core/auth.py:62-83`:
    HttpOnly; dev `Lax` (valid over plain HTTP on localhost), production
    `None` + `Secure` for genuinely cross-site delivery over HTTPS.
    """
    from app.core.config import settings

    is_prod = settings.APP_ENV not in ("development", "testing")
    return {
        "key": ADMIN_SESSION_COOKIE,
        "httponly": True,
        "samesite": "none" if is_prod else "lax",
        "secure": is_prod,
        "path": "/",
        "max_age": ADMIN_SESSION_ABSOLUTE_HOURS * 60 * 60,
    }


def clear_admin_session_cookie_kwargs() -> dict[str, Any]:
    kwargs = admin_session_cookie_kwargs()
    return {
        "key": ADMIN_SESSION_COOKIE,
        "path": kwargs["path"],
        "samesite": kwargs["samesite"],
        "secure": kwargs["secure"],
        "httponly": kwargs["httponly"],
    }


async def get_current_admin(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AdminUser:
    """Resolve the admin identity from the opaque session cookie.

    Lookup: cookie -> SHA-256 -> `admin_sessions` join `admin_users` where
    `revoked_at IS NULL AND expires_at > now AND is_active` -> else 401.
    Sliding renewal extends `expires_at` while < 2 h remain, capped at 24 h
    from session creation. The resolved session row is also exposed via
    `request.state.admin_session` for handlers that need `expires_at`.
    """
    raw_token = request.cookies.get(ADMIN_SESSION_COOKIE)
    if not raw_token:
        raise _NOT_AUTHENTICATED

    result = await db.execute(
        select(AdminSession, AdminUser)
        .join(AdminUser, AdminSession.admin_id == AdminUser.id)
        .where(AdminSession.token_hash == hash_admin_token(raw_token))
    )
    row = result.first()
    if row is None:
        raise _NOT_AUTHENTICATED

    session, admin = row
    now = datetime.now(UTC)
    if session.revoked_at is not None:
        raise _NOT_AUTHENTICATED
    if _as_utc(session.expires_at) <= now or not admin.is_active:
        raise _NOT_AUTHENTICATED

    if _as_utc(session.expires_at) - now < timedelta(
        hours=ADMIN_SESSION_SLIDING_HOURS
    ):
        cap = _as_utc(session.created_at) + timedelta(
            hours=ADMIN_SESSION_MAX_HOURS
        )
        renewed = min(
            now + timedelta(hours=ADMIN_SESSION_ABSOLUTE_HOURS),
            cap,
        )
        if renewed > _as_utc(session.expires_at):
            session.expires_at = renewed
    session.last_seen_at = now
    await db.commit()

    request.state.admin_session = session
    return admin


async def get_current_admin_or_403(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AdminUser:
    """Admin-only guard for legacy user-namespace routes.

    Used by `PUT /providers/{slug}`, `POST /providers/{slug}/toggle` and
    `POST /providers/{slug}/sync-models` (the verified privilege-escalation
    hole). An authenticated non-admin gets `403`; anonymous callers `401`.
    """
    try:
        return await get_current_admin(request, db)
    except HTTPException as exc:
        if exc.status_code != status.HTTP_401_UNAUTHORIZED:
            raise

    try:
        await get_current_user(request, None, db)
    except HTTPException:
        raise _NOT_AUTHENTICATED
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin privileges required",
    )
