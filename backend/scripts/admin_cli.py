"""Provisioning / recovery CLI for the /admin control center.

Run from the backend directory:
    python scripts/admin_cli.py <command>

Commands:
    create [username]      Create an admin (username/password from
                           ADMIN_BOOTSTRAP_USERNAME / ADMIN_BOOTSTRAP_PASSWORD
                           env vars or interactive prompt)
    set-password <username>   Rotate password and revoke all sessions
    deactivate <username>  Disable the admin and revoke all sessions
    activate <username>    Re-enable the admin and clear the lockout
    list                   List admins (no hashes/secrets)
    cleanup                Purge expired/revoked admin sessions
    maintenance off        Headless recovery: disable maintenance mode

Secrets are read from env vars or a hidden prompt — never from argv —
and are never echoed. Every mutation writes an audit_logs row
(actor_type="system").
"""

import argparse
import asyncio
import getpass
import logging
import os
import sys
from datetime import UTC, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.admin import AdminUser
from app.models.platform import PlatformSetting
from app.services import admin_auth
from app.services.admin_audit import admin_audit

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("admin_cli")


def _read_new_password(env_var: str) -> str:
    env_value = os.environ.get(env_var)
    if env_value:
        return env_value
    first = getpass.getpass("New admin password: ")
    if not first:
        raise SystemExit("Aborted: empty password.")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        raise SystemExit("Aborted: passwords do not match.")
    return first


async def _create(args: argparse.Namespace) -> None:
    username = (
        args.username or os.environ.get("ADMIN_BOOTSTRAP_USERNAME") or ""
    ).strip()
    if not username:
        username = input("Admin username: ").strip()
    if not username:
        raise SystemExit("Aborted: username is required.")

    password_hash = os.environ.get("ADMIN_BOOTSTRAP_PASSWORD_HASH") or None
    password = None
    if not password_hash:
        password = os.environ.get("ADMIN_BOOTSTRAP_PASSWORD") or None
        if not password:
            password = _read_new_password("ADMIN_BOOTSTRAP_PASSWORD")

    async with AsyncSessionLocal() as db:
        existing = await admin_auth.get_admin_by_username(db, username)
        if existing is not None:
            raise SystemExit(f"Aborted: admin '{username}' already exists.")
        admin = await admin_auth.provision_admin(
            db,
            username=username,
            password=password,
            password_hash=password_hash,
        )
        await admin_audit(
            db,
            action="admin.bootstrap",
            entity_type="admin_user",
            entity_id=str(admin.id),
            actor_id="cli",
            details={"source": "cli"},
        )
        logger.info("Admin '%s' created.", admin.username)


async def _set_password(args: argparse.Namespace) -> None:
    new_password = _read_new_password("ADMIN_NEW_PASSWORD")
    async with AsyncSessionLocal() as db:
        admin = await _require_admin(db, args.username)
        await admin_auth.set_admin_password(db, admin, new_password)
        await admin_audit(
            db,
            action="admin.set_password",
            entity_type="admin_user",
            entity_id=str(admin.id),
            actor_id="cli",
        )
        logger.info(
            "Password rotated for '%s'; all prior sessions revoked.", admin.username
        )


async def _set_active(args: argparse.Namespace, *, active: bool) -> None:
    async with AsyncSessionLocal() as db:
        admin = await _require_admin(db, args.username)
        try:
            await admin_auth.set_admin_active(db, admin, active=active)
        except admin_auth.LastActiveAdminError as exc:
            raise SystemExit(f"Aborted: {exc}.") from exc
        state = "activated" if active else "deactivated (sessions revoked)"
        logger.info("Admin '%s' %s.", admin.username, state)


async def _list(_: argparse.Namespace) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(AdminUser).order_by(AdminUser.username))
        admins = result.scalars().all()
        if not admins:
            logger.info("No admins provisioned.")
            return
        for admin in admins:
            logger.info(
                "%s | active=%s | locked_until=%s | last_login_at=%s | created_at=%s",
                admin.username,
                admin.is_active,
                admin.locked_until or "-",
                admin.last_login_at or "-",
                admin.created_at or "-",
            )


async def _cleanup(_: argparse.Namespace) -> None:
    async with AsyncSessionLocal() as db:
        purged = await admin_auth.purge_stale_sessions(db)
        await admin_audit(
            db,
            action="admin.sessions_purged",
            entity_type="admin_session",
            entity_id="all",
            actor_id="cli",
            details={"purged": purged},
            commit=False,
        )
        await db.commit()
        logger.info("Purged %d stale admin session(s).", purged)


async def _maintenance_off(_: argparse.Namespace) -> None:
    """Headless recovery: disable maintenance mode without the admin UI."""
    now_iso = datetime.now(UTC).isoformat()
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PlatformSetting).where(PlatformSetting.key == "maintenance")
        )
        row = result.scalars().first()
        if row is None:
            row = PlatformSetting(
                key="maintenance",
                value={
                    "enabled": False,
                    "changed_by": "cli",
                    "changed_at": now_iso,
                },
                version=1,
            )
            db.add(row)
        else:
            value = dict(row.value or {})
            value.update(
                {"enabled": False, "changed_by": "cli", "changed_at": now_iso}
            )
            row.value = value
            row.version = int(row.version or 1) + 1
        await admin_audit(
            db,
            action="admin.maintenance_disabled",
            entity_type="platform_setting",
            entity_id="maintenance",
            actor_id="cli",
            details={"source": "cli_recovery"},
            commit=False,
        )
        await db.commit()
        logger.info("Maintenance mode disabled.")


async def _require_admin(db, username: str) -> AdminUser:
    admin = await admin_auth.get_admin_by_username(db, username)
    if admin is None:
        raise SystemExit(f"Aborted: admin '{username}' not found.")
    return admin


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="admin_cli.py",
        description="Provision and recover /admin accounts (no secrets in argv).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="Create an admin account")
    p_create.add_argument("username", nargs="?", default=None)
    p_create.set_defaults(func=_create)

    p_setpw = sub.add_parser(
        "set-password", help="Rotate password (revokes all sessions)"
    )
    p_setpw.add_argument("username")
    p_setpw.set_defaults(func=_set_password)

    p_deactivate = sub.add_parser(
        "deactivate", help="Disable an admin (revokes all sessions)"
    )
    p_deactivate.add_argument("username")
    p_deactivate.set_defaults(func=lambda a: _set_active(a, active=False))

    p_activate = sub.add_parser("activate", help="Re-enable an admin, clear lockout")
    p_activate.add_argument("username")
    p_activate.set_defaults(func=lambda a: _set_active(a, active=True))

    p_list = sub.add_parser("list", help="List admins")
    p_list.set_defaults(func=_list)

    p_cleanup = sub.add_parser("cleanup", help="Purge stale admin sessions")
    p_cleanup.set_defaults(func=_cleanup)

    p_maint = sub.add_parser(
        "maintenance", help="Maintenance-mode recovery (headless)"
    )
    p_maint.add_argument("action", choices=["off"])
    p_maint.set_defaults(func=_maintenance_off)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
