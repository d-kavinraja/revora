from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import bcrypt
import jwt

from app.core.config import settings

# JWT configuration
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 1 day for development

# Cookie name shared with the frontend edge gate (proxy.ts) and the
# backend cookie reader. The backend (not JS) is the only writer.
SESSION_COOKIE_NAME = "revora_auth_token"
SESSION_COOKIE_MAX_AGE = 60 * 60 * 24  # 1 day, mirrors token expiry


def get_password_hash(password: str) -> str:
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )
    except Exception:
        return False


def create_access_token(
    subject: str | Any,
    expires_delta: timedelta | None = None,
    token_version: int = 0,
) -> str:
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode = {
        "exp": expire,
        "sub": str(subject),
        # jti gives each token a unique identity; tv binds it to the user's
        # current session generation (bumped on logout for revocation).
        "jti": str(uuid4()),
        "tv": int(token_version or 0),
    }
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[ALGORITHM])


def session_cookie_kwargs() -> dict[str, Any]:
    """Flags for the backend-written session cookie.

    HttpOnly removes page-JS access (the XSS fix). SameSite policy is
    environment-dependent:
      - Development/testing: SameSite=Lax. The frontend is reached through a
        same-origin BFF and localhost:3000 <-> localhost:8000 are the same
        site, so Lax flows while staying valid over plain HTTP. (SameSite=None
        REQUIRES Secure, so an insecure None cookie is rejected by the browser
        even on localhost — the original source of the login/logout loop.)
      - Production: SameSite=None + Secure, required for genuinely
        cross-site delivery over HTTPS.
    """
    is_prod = settings.APP_ENV not in ("development", "testing")
    return {
        "key": SESSION_COOKIE_NAME,
        "httponly": True,
        "samesite": "none" if is_prod else "lax",
        "secure": is_prod,
        "path": "/",
        "max_age": SESSION_COOKIE_MAX_AGE,
    }
