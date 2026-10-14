from datetime import timedelta

import httpx
import secrets
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    SESSION_COOKIE_NAME,
    create_access_token,
    session_cookie_kwargs,
    verify_password,
)
from app.core.config import settings
from app.core.deps import get_current_user
from app.db.session import get_db
from app.middleware.rate_limit import limiter
from app.models.user import User as UserModel
from app.schemas.user import User, UserCreate
from app.services.sync_engine import _login_reconciliation
from app.services.user_service import user_service

router = APIRouter()

# OAuth login-CSRF binding. The `oauth_state` cookie is HttpOnly,
# short-lived (10 min), random per attempt, and single-use: it is cleared
# on every exchange attempt, success or failure.
OAUTH_STATE_COOKIE = "oauth_state"
OAUTH_STATE_TTL_S = 10 * 60


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(value=token, **session_cookie_kwargs())


def _clear_session_cookie(response: Response) -> None:
    # Must match the cookie attributes used when setting it for proper deletion.
    kwargs = session_cookie_kwargs()
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path=kwargs["path"],
        samesite=kwargs["samesite"],
        secure=kwargs["secure"],
        httponly=kwargs["httponly"],
    )


def _verify_oauth_state(request: Request, response: Response, provided: str | None) -> None:
    """Reject the exchange unless the caller proves it started the flow.

    In non-production environments a missing state is tolerated so local
    dev/tests keep working; production always requires it.
    """
    stored = request.cookies.get(OAUTH_STATE_COOKIE)
    # Single-use in all cases: burn the cookie on every attempt.
    is_prod = settings.APP_ENV not in ("development", "testing")
    response.delete_cookie(
        key=OAUTH_STATE_COOKIE,
        path="/",
        samesite="none",
        secure=is_prod,
        httponly=True,
    )
    if not stored or not provided:
        if is_prod:
            raise HTTPException(
                status_code=400,
                detail="Invalid or expired login session. Please try signing in again.",
            )
        return
    if not secrets.compare_digest(stored, provided):
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired login session. Please try signing in again.",
        )


class GitHubLoginRequest(BaseModel):
    code: str
    redirect_uri: str | None = None
    state: str | None = None


def _github_error(response: Response, status_code: int, detail: str) -> JSONResponse:
    """Error response that preserves cookies staged on the injected response.

    Raising HTTPException discards Set-Cookie headers staged earlier (e.g. the
    single-use oauth_state burn in _verify_oauth_state), leaving stale cookies
    in the browser. Returning keeps them.
    """
    error_resp = JSONResponse(status_code=status_code, content={"detail": detail})
    for staged in response.headers.getlist("set-cookie"):
        error_resp.headers.append("set-cookie", staged)
    return error_resp


@router.post("/login", response_model=dict)
@limiter.limit("5/minute")
async def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    user = await user_service.get_by_email(db, form_data.username)
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=60 * 24)
    access_token = create_access_token(
        subject=user.id,
        expires_delta=access_token_expires,
        token_version=int(getattr(user, "token_version", 0) or 0),
    )
    # Backend-written HttpOnly session cookie (page JS can never read it).
    _set_session_cookie(response, access_token)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "image": user.avatar_url,
            "github_username": user.github_username,
        },
    }


@router.post("/register", response_model=User, status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")
async def register(
    request: Request, user_in: UserCreate, db: AsyncSession = Depends(get_db)
):
    user = await user_service.get_by_email(db, email=user_in.email)
    if user:
        # Generic message (no confirmation of which field collided).
        # Full enumeration fix needs a neutral 202 + email flow; kept
        # response_model=User so live frontend register keeps working.
        raise HTTPException(
            status_code=400,
            detail="Unable to create account with the provided details.",
        )
    user = await user_service.create(db, user_in=user_in)
    return user


@router.post("/github", response_model=dict)
@limiter.limit("10/minute")
async def github_login(
    request: Request,
    response: Response,
    payload: GitHubLoginRequest,
    db: AsyncSession = Depends(get_db),
    background_tasks: BackgroundTasks = None,
):
    """Exchanges a GitHub OAuth code for a JWT, linking or registering the user."""
    if not settings.GITHUB_CLIENT_ID or not settings.GITHUB_CLIENT_SECRET:
        raise HTTPException(
            status_code=500, detail="GitHub OAuth is not configured on the server."
        )

    # 0. Login-CSRF binding: prove this browser started the authorize flow.
    _verify_oauth_state(request, response, payload.state)

    # 1. Exchange code for access token
    async with httpx.AsyncClient(timeout=30.0) as client:
        exchange_data = {
            "client_id": settings.GITHUB_CLIENT_ID,
            "client_secret": settings.GITHUB_CLIENT_SECRET,
            "code": payload.code,
        }
        if payload.redirect_uri:
            exchange_data["redirect_uri"] = payload.redirect_uri

        token_res = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data=exchange_data,
        )
        if not token_res.is_success:
            return _github_error(
                response,
                400,
                "Failed to exchange GitHub authorization code. Please verify GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET in backend/.env match your GitHub App.",
            )

        token_data = token_res.json()
        access_token = token_data.get("access_token")
        if not access_token:
            err_desc = token_data.get("error_description") or ""
            err_code = token_data.get("error") or ""
            if (
                "incorrect or expired" in err_desc.lower()
                or "bad_verification_code" in err_code.lower()
            ):
                return _github_error(
                    response,
                    400,
                    "GitHub returned: Invalid or expired code. This usually happens because GITHUB_CLIENT_ID or GITHUB_CLIENT_SECRET in your backend/.env does not match the GitHub App you are authorizing with, or because you need to restart uvicorn after modifying the .env file.",
                )
            return _github_error(
                response,
                400,
                token_data.get(
                    "error_description", "Invalid GitHub authorization code."
                ),
            )

        # 2. Fetch GitHub user profile
        user_res = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        if not user_res.is_success:
            return _github_error(
                response, 400, "Failed to retrieve user profile from GitHub."
            )

        gh_user = user_res.json()
        github_id = gh_user.get("id")
        github_username = gh_user.get("login")
        name = gh_user.get("name") or github_username
        avatar_url = gh_user.get("avatar_url")
        email = gh_user.get("email")

        # 3. Fetch user email if not public in profile
        if not email:
            try:
                emails_res = await client.get(
                    "https://api.github.com/user/emails",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/json",
                    },
                )
                if emails_res.is_success:
                    emails_list = emails_res.json()
                    # Find primary email
                    primary_email = next(
                        (e["email"] for e in emails_list if e.get("primary")), None
                    )
                    if not primary_email and emails_list:
                        primary_email = emails_list[0]["email"]
                    email = primary_email
            except Exception:
                pass

        if not email:
            email = f"{github_id}+{github_username}@users.noreply.github.com"

    # 4. Authenticate, link, or register user in DB
    # Check by github_id
    result = await db.execute(select(UserModel).where(UserModel.github_id == github_id))
    user = result.scalars().first()

    if not user:
        # Check by email to link existing user
        result = await db.execute(select(UserModel).where(UserModel.email == email))
        user = result.scalars().first()
        if user:
            return _github_error(
                response,
                400,
                "An account with this email already exists. Please log in with your password to link your GitHub account.",
            )
        else:
            # Register new user
            user = UserModel(
                name=name,
                email=email,
                github_id=github_id,
                github_username=github_username,
                avatar_url=avatar_url,
                is_verified=True,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

    # 5. Generate JWT token
    access_token_expires = timedelta(minutes=60 * 24)
    jwt_token = create_access_token(
        subject=user.id,
        expires_delta=access_token_expires,
        token_version=int(getattr(user, "token_version", 0) or 0),
    )
    # Backend-written HttpOnly session cookie (page JS can never read it).
    _set_session_cookie(response, jwt_token)

    # 6. Trigger lightweight background reconciliation (non-blocking)
    if background_tasks is not None:
        background_tasks.add_task(_login_reconciliation, user.id)

    return {
        "access_token": jwt_token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "image": user.avatar_url,
            "github_username": user.github_username,
        },
    }


@router.get("/config", response_model=dict)
async def get_auth_config():
    """Returns public authentication configurations, like the GitHub Client ID."""
    return {"github_client_id": settings.GITHUB_CLIENT_ID}


@router.get("/oauth/start", response_model=dict)
@limiter.limit("10/minute")
async def oauth_start(request: Request, response: Response):
    """Mint a single-use OAuth login-CSRF state for this browser.

    The frontend appends ``state`` to the GitHub authorize URL; the
    matching HttpOnly cookie is verified (and burned) at POST /auth/github.
    """
    if not settings.GITHUB_CLIENT_ID:
        raise HTTPException(
            status_code=500, detail="GitHub OAuth is not configured on the server."
        )
    state = secrets.token_urlsafe(32)
    is_prod = settings.APP_ENV not in ("development", "testing")
    # SameSite=None allows the cookie to be sent on cross-origin POST from
    # the callback page (localhost:3000 -> 127.0.0.1:8000). Modern browsers
    # permit SameSite=None; Secure=False on localhost for development.
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=state,
        httponly=True,
        samesite="none",
        secure=is_prod,  # Secure only in production (requires HTTPS)
        path="/",
        max_age=OAUTH_STATE_TTL_S,
    )
    return {"state": state}


@router.get("/me", response_model=User)
async def get_me(current_user: UserModel = Depends(get_current_user)):
    """Current session identity (drives cookie-session restore after reload)."""
    return User.model_validate(current_user, from_attributes=True)


@router.post("/logout", response_model=dict)
async def logout(
    response: Response,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke every session by bumping token_version, then clear the cookie."""
    current_tv = int(getattr(current_user, "token_version", 0) or 0)
    current_user.token_version = current_tv + 1
    db.add(current_user)
    await db.commit()
    _clear_session_cookie(response)
    return {"status": "logged_out"}
