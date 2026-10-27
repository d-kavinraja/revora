"""Admin authentication endpoints (`/api/v1/admin/auth/*`).

Login is rate-limited, lockout-guarded and returns generic errors; the
opaque session token is delivered only as an HttpOnly cookie. The admin
namespace is exempt from maintenance middleware (S9) — these endpoints
keep working while maintenance mode is enabled.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_password
from app.core.deps_admin import (
    admin_session_cookie_kwargs,
    clear_admin_session_cookie_kwargs,
    get_current_admin,
)
from app.db.session import get_db
from app.middleware.rate_limit import limiter
from app.models.admin import AdminUser
from app.schemas.admin import AdminLoginRequest, AdminLoginResponse, AdminSessionRead
from app.services import admin_auth
from app.services.admin_audit import admin_audit

router = APIRouter()


def _invalid_credentials() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
    )


def _too_many_attempts() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many failed attempts. Try again later.",
    )


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/login", response_model=AdminLoginResponse)
@limiter.limit("5/minute")
async def admin_login(
    request: Request,
    response: Response,
    payload: AdminLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    admin = await admin_auth.get_admin_by_username(db, payload.username)
    attempted_actor = admin_auth.normalize_username(payload.username)

    # Evaluate the password BEFORE consulting lock state. An unauthenticated
    # caller must never be able to distinguish "unknown user" from "wrong
    # password" or "account locked" (B5 no-enumeration contract); a distinct
    # 429 is therefore only ever returned once the *correct* password has
    # already been supplied.
    password_ok = (
        verify_password(payload.password, admin.password_hash)
        if admin is not None
        else admin_auth.verify_password_timing_guard(payload.password)
    )
    if admin is None or not password_ok or not admin.is_active:
        if admin is not None and admin_auth.is_admin_locked(admin):
            # Already locked: record the attempt but never extend the window
            # (prevents an unauthenticated actor from pinning the lock), and
            # keep the response indistinguishable from an invalid login.
            await admin_audit(
                db,
                action="admin.login_locked",
                entity_type="admin_user",
                entity_id=str(admin.id),
                outcome="failure",
                actor_id=attempted_actor,
                details={"reason": "locked"},
                request=request,
            )
            raise _invalid_credentials()

        locked_now = await admin_auth.record_login_failure(db, admin)
        await admin_audit(
            db,
            action="admin.login_locked" if locked_now else "admin.login_failure",
            entity_type="admin_user",
            entity_id=str(admin.id) if admin else attempted_actor,
            outcome="failure",
            actor_id=attempted_actor,
            details={"reason": "invalid_credentials"},
            request=request,
        )
        raise _invalid_credentials()

    if admin_auth.is_admin_locked(admin):
        # Correct credentials, but the account is within its lock window. Only
        # a caller who already knows the password can observe this state.
        await admin_audit(
            db,
            action="admin.login_locked",
            entity_type="admin_user",
            entity_id=str(admin.id),
            outcome="failure",
            actor_id=attempted_actor,
            details={"reason": "locked"},
            request=request,
        )
        raise _too_many_attempts()

    raw_token, expires_at = await admin_auth.record_login_success(
        db,
        admin,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    await admin_audit(
        db,
        action="admin.login_success",
        entity_type="admin_user",
        entity_id=str(admin.id),
        admin=admin,
        request=request,
    )
    response.set_cookie(value=raw_token, **admin_session_cookie_kwargs())
    return AdminLoginResponse(username=admin.username, expires_at=expires_at)


@router.get("/session", response_model=AdminSessionRead)
async def admin_session(
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
):
    session = getattr(request.state, "admin_session", None)
    return AdminSessionRead(username=admin.username, expires_at=session.expires_at)


@router.post("/logout", response_model=dict)
async def admin_logout(
    request: Request,
    response: Response,
    admin: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    session = getattr(request.state, "admin_session", None)
    session.revoked_at = datetime.now(UTC)
    db.add(session)
    await db.commit()

    response.delete_cookie(**clear_admin_session_cookie_kwargs())
    await admin_audit(
        db,
        action="admin.logout",
        entity_type="admin_user",
        entity_id=str(admin.id),
        admin=admin,
        request=request,
    )
    return {"status": "logged_out"}
