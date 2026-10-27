import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import SESSION_COOKIE_NAME, decode_access_token
from app.db.session import get_db
from app.models.user import User

# auto_error=False: the cookie reader below provides the fallback so
# cookie-authenticated browsers (no Authorization header) are accepted.
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login", auto_error=False
)

#: Activity instrumentation throttle (phase 7, §3.4): at most one
#: `users.last_active_at` write per user per this interval.
ACTIVITY_TOUCH_INTERVAL = timedelta(minutes=5)


def _activity_touch_due(last_active_at: datetime | None, now: datetime) -> bool:
    if last_active_at is None:
        return True
    if last_active_at.tzinfo is None:
        # SQLite round-trips naive values; stored values are UTC wall time.
        last_active_at = last_active_at.replace(tzinfo=UTC)
    return now - last_active_at >= ACTIVITY_TOUCH_INTERVAL


async def _token_from_request(request: Request, header_token: str | None) -> str | None:
    if header_token:
        return header_token
    # Backend-set HttpOnly cookie (written by /auth/login and /auth/github).
    cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
    return cookie_token or None


async def get_current_user(
    request: Request,
    header_token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        token = await _token_from_request(request, header_token)
        if not token:
            raise credentials_exception
        payload = decode_access_token(token)
        user_id_str: str | None = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
        user_id = uuid.UUID(user_id_str)
        token_tv = int(payload.get("tv", 0) or 0)
    except HTTPException:
        raise
    except Exception:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if user is None:
        raise credentials_exception
    # Admin disable enforcement (B14): a disabled account is refused with a
    # distinct 403, checked BEFORE token_version so the live cookie of a
    # just-disabled user yields "Account disabled" (not a generic 401).
    if (user.status or "active") != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled"
        )
    # Session revocation: logout bumps user.token_version, killing all
    # previously minted tokens (they carry the older tv).
    user_tv = int(getattr(user, "token_version", 0) or 0)
    if token_tv != user_tv:
        raise credentials_exception

    # Activity tracking (phase 7, §3.4): throttled `last_active_at` touch
    # (max one write per user per 5 minutes). Fail-open — analytics writes
    # must never break an authenticated request.
    # Activity tracking (phase 7, §3.4): throttled `last_active_at` touch
    # (max one write per user per 5 minutes). Fail-open — analytics writes
    # must never break an authenticated request.
    now = datetime.now(UTC)
    if _activity_touch_due(user.last_active_at, now):
        try:
            user.last_active_at = now
            db.add(user)
            await db.commit()
            await db.refresh(user)
        except Exception:
            await db.rollback()
    return user
