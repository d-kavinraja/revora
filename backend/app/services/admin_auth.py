"""Admin authentication workflows: lockout, opaque sessions, provisioning.

Shared by the admin auth endpoints, the startup env bootstrap and the
provisioning CLI (`backend/scripts/admin_cli.py`). Raw session tokens are
returned exactly once and only their SHA-256 hash is persisted.
"""

import secrets
import uuid as uuid_lib
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_password_hash, verify_password
from app.core.deps_admin import (
    ADMIN_SESSION_ABSOLUTE_HOURS,
    _as_utc,
    hash_admin_token,
)
from app.models.admin import AdminSession, AdminUser
from app.services.admin_audit import admin_audit

FAILED_LOGIN_LOCK_THRESHOLD = 5
LOGIN_LOCK_MINUTES = 15

SESSION_PURGE_EXPIRED_DAYS = 30
SESSION_PURGE_REVOKED_DAYS = 7


class LastActiveAdminError(RuntimeError):
    """Refusal to deactivate the only remaining active admin account.

    B15 realized at the admin-account layer: console identities
    (`admin_users`) are structurally separate from app users, so the
    "self / last-admin" safeguard protects the control plane itself.
    """


def normalize_username(username: str) -> str:
    """Case-normalized storage/lookup key (usernames are case-insensitive)."""
    return username.strip().lower()


async def get_admin_by_username(
    db: AsyncSession, username: str
) -> AdminUser | None:
    result = await db.execute(
        select(AdminUser).where(AdminUser.username == normalize_username(username))
    )
    return result.scalars().first()


def is_admin_locked(admin: AdminUser | None) -> bool:
    if admin is None or admin.locked_until is None:
        return False
    return _as_utc(admin.locked_until) > datetime.now(UTC)


async def provision_admin(
    db: AsyncSession,
    *,
    username: str,
    password: str | None = None,
    password_hash: str | None = None,
) -> AdminUser:
    """Create an admin. Exactly one of password / password_hash is required.

    Passwords are bcrypt-hashed before storing; raw secrets are never kept.
    """
    if bool(password) == bool(password_hash):
        raise ValueError("provide exactly one of password or password_hash")
    admin = AdminUser(
        username=normalize_username(username),
        password_hash=password_hash or get_password_hash(password or ""),
        is_active=True,
    )
    db.add(admin)
    await db.commit()
    await db.refresh(admin)
    return admin


async def set_admin_password(
    db: AsyncSession, admin: AdminUser, new_password: str
) -> None:
    """Rotate an admin password and revoke every session of that admin."""
    admin.password_hash = get_password_hash(new_password)
    admin.failed_login_count = 0
    admin.locked_until = None
    await revoke_admin_sessions(db, admin=admin)
    await db.commit()


async def revoke_admin_sessions(db: AsyncSession, *, admin: AdminUser) -> int:
    now = datetime.now(UTC)
    result = await db.execute(
        select(AdminSession).where(
            AdminSession.admin_id == admin.id,
            AdminSession.revoked_at.is_(None),
        )
    )
    count = 0
    for session in result.scalars().all():
        session.revoked_at = now
        count += 1
    return count


async def count_active_admins(
    db: AsyncSession, *, exclude_id: uuid_lib.UUID | None = None
) -> int:
    stmt = (
        select(func.count())
        .select_from(AdminUser)
        .where(AdminUser.is_active.is_(True))
    )
    if exclude_id is not None:
        stmt = stmt.where(AdminUser.id != exclude_id)
    return int((await db.execute(stmt)).scalar_one())


async def set_admin_active(
    db: AsyncSession,
    admin: AdminUser,
    *,
    active: bool,
    actor_id: str = "cli",
    actor_type: str | None = None,
) -> None:
    """Activate/deactivate an admin with the last-active-admin guard (B15).

    Deactivating the only remaining active admin is refused, audited with
    ``outcome=failure`` and raises :class:`LastActiveAdminError`. Successful
    transitions revoke all sessions of the target admin and are audited.
    """
    if not active and admin.is_active:
        remaining = await count_active_admins(db, exclude_id=admin.id)
        if remaining == 0:
            await admin_audit(
                db,
                action="admin.deactivate_blocked",
                entity_type="admin_user",
                entity_id=str(admin.id),
                outcome="failure",
                actor_id=actor_id,
                actor_type=actor_type,
                details={"reason": "last_active_admin"},
                commit=False,
            )
            await db.commit()
            raise LastActiveAdminError(
                "cannot deactivate the last active admin"
            )

    admin.is_active = active
    if active:
        admin.failed_login_count = 0
        admin.locked_until = None
    else:
        await revoke_admin_sessions(db, admin=admin)
    await db.commit()
    await admin_audit(
        db,
        action="admin.activated" if active else "admin.deactivated",
        entity_type="admin_user",
        entity_id=str(admin.id),
        actor_id=actor_id,
        actor_type=actor_type,
    )


async def create_admin_session(
    db: AsyncSession,
    *,
    admin: AdminUser,
    ip_address: str | None,
    user_agent: str | None,
) -> tuple[str, datetime]:
    """Mint an opaque 256-bit session token; persist only its SHA-256 hash.

    Returns (raw_token, expires_at). The caller commits.
    """
    raw_token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    expires_at = now + timedelta(hours=ADMIN_SESSION_ABSOLUTE_HOURS)
    session = AdminSession(
        admin_id=admin.id,
        token_hash=hash_admin_token(raw_token),
        expires_at=expires_at,
        last_seen_at=now,
        ip_address=ip_address,
        user_agent=(user_agent[:500] if user_agent else None),
    )
    db.add(session)
    return raw_token, expires_at


async def record_login_failure(
    db: AsyncSession, admin: AdminUser | None
) -> bool:
    """Increment the failure counter; engage the lockout on threshold.

    Returns True when this failure just engaged the lockout.
    """
    if admin is None:
        return False
    admin.failed_login_count = int(admin.failed_login_count or 0) + 1
    locked_now = False
    if admin.failed_login_count >= FAILED_LOGIN_LOCK_THRESHOLD:
        admin.locked_until = datetime.now(UTC) + timedelta(
            minutes=LOGIN_LOCK_MINUTES
        )
        locked_now = True
    await db.commit()
    return locked_now


async def record_login_success(
    db: AsyncSession,
    admin: AdminUser,
    *,
    ip_address: str | None,
    user_agent: str | None,
) -> tuple[str, datetime]:
    """Reset counters, stamp last_login_at, mint the session. Caller commits."""
    admin.failed_login_count = 0
    admin.locked_until = None
    admin.last_login_at = datetime.now(UTC)
    return await create_admin_session(
        db, admin=admin, ip_address=ip_address, user_agent=user_agent
    )


async def purge_stale_sessions(db: AsyncSession) -> int:
    """Delete sessions expired > 30 d ago or revoked > 7 d ago."""
    now = datetime.now(UTC)
    result = await db.execute(
        delete(AdminSession).where(
            or_(
                AdminSession.expires_at
                < now - timedelta(days=SESSION_PURGE_EXPIRED_DAYS),
                AdminSession.revoked_at
                < now - timedelta(days=SESSION_PURGE_REVOKED_DAYS),
            )
        )
    )
    await db.commit()
    return result.rowcount or 0


@lru_cache(maxsize=1)
def _timing_guard_hash() -> str:
    return get_password_hash("timing-guard-placeholder")


def verify_password_timing_guard(password: str) -> bool:
    """Constant-cost False for unknown usernames (no timing enumeration)."""
    return verify_password(password, _timing_guard_hash())
