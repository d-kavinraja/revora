import uuid

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
    # Session revocation: logout bumps user.token_version, killing all
    # previously minted tokens (they carry the older tv).
    user_tv = int(getattr(user, "token_version", 0) or 0)
    if token_tv != user_tv:
        raise credentials_exception
    return user
