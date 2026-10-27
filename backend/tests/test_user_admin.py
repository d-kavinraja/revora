"""Phase 3 — user administration tests.

Covers: B14 (disable blocks /auth/me with 403 and bumps token_version),
enable restores access (fresh token needed — old tokens stay dead),
revoke-sessions, 404/422 boundaries, audit rows (B29 subset: exactly one
row, admin actor, outcome, no secrets) and the B15 realization at the
admin-account layer: the last active admin cannot be deactivated
(``admin.deactivate_blocked`` audit with outcome=failure).
"""

import uuid

import pytest
from sqlalchemy import select

from app.core.auth import SESSION_COOKIE_NAME, create_access_token
from app.models.admin import AdminUser
from app.models.audit import AuditLog
from app.services import admin_auth

USERS_URL = "/api/v1/admin/users"
ME_URL = "/api/v1/auth/me"


def _use_user_cookie(client, token: str) -> None:
    client.cookies.set(SESSION_COOKIE_NAME, token)


async def _audit_rows(db, action: str):
    result = await db.execute(select(AuditLog).where(AuditLog.action == action))
    return result.scalars().all()


async def test_disable_user_blocks_access_and_revokes_sessions(
    test_db, admin_client, admin_user, mock_user, user_auth_token
):
    _use_user_cookie(admin_client, user_auth_token)
    assert admin_client.get(ME_URL).status_code == 200

    response = admin_client.post(
        f"{USERS_URL}/{mock_user.id}/disable",
        json={"reason": "ToS violation"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "disabled"
    assert body["disabled_at"] is not None

    # Live cookie dies: distinct 403, not a generic 401.
    blocked = admin_client.get(ME_URL)
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "Account disabled"

    await test_db.refresh(mock_user)
    assert mock_user.status == "disabled"
    assert mock_user.disabled_at is not None
    assert mock_user.token_version == 1

    rows = await _audit_rows(test_db, "user.disable")
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_type == "admin"
    assert row.actor_id == admin_user.username
    assert row.entity_type == "user"
    assert row.entity_id == str(mock_user.id)
    assert row.details["outcome"] == "success"
    assert row.details["reason"] == "ToS violation"


async def test_enable_restores_access_with_fresh_token(
    test_db, admin_client, admin_user, mock_user, user_auth_token
):
    disable = admin_client.post(
        f"{USERS_URL}/{mock_user.id}/disable", json={"reason": "abuse"}
    )
    assert disable.status_code == 200

    enable = admin_client.post(f"{USERS_URL}/{mock_user.id}/enable")
    assert enable.status_code == 200, enable.text
    body = enable.json()
    assert body["status"] == "active"
    assert body["disabled_at"] is None

    # Old token stays dead (tv bumped at disable) …
    _use_user_cookie(admin_client, user_auth_token)
    assert admin_client.get(ME_URL).status_code == 401

    # … a fresh login-time token works again.
    await test_db.refresh(mock_user)
    fresh = create_access_token(
        subject=str(mock_user.id),
        token_version=int(mock_user.token_version),
    )
    _use_user_cookie(admin_client, fresh)
    assert admin_client.get(ME_URL).status_code == 200

    rows = await _audit_rows(test_db, "user.enable")
    assert len(rows) == 1
    assert rows[0].details["outcome"] == "success"


async def test_revoke_sessions_bumps_token_version(
    test_db, admin_client, admin_user, mock_user, user_auth_token
):
    response = admin_client.post(f"{USERS_URL}/{mock_user.id}/revoke-sessions")
    assert response.status_code == 200, response.text
    assert response.json() == {"revoked": True}

    _use_user_cookie(admin_client, user_auth_token)
    assert admin_client.get(ME_URL).status_code == 401

    await test_db.refresh(mock_user)
    assert mock_user.status == "active"
    assert mock_user.token_version == 1

    fresh = create_access_token(
        subject=str(mock_user.id),
        token_version=int(mock_user.token_version),
    )
    _use_user_cookie(admin_client, fresh)
    assert admin_client.get(ME_URL).status_code == 200

    rows = await _audit_rows(test_db, "user.revoke_sessions")
    assert len(rows) == 1
    assert rows[0].details["outcome"] == "success"


@pytest.mark.parametrize(
    "suffix,payload",
    [
        ("/disable", {"reason": "x"}),
        ("/enable", None),
        ("/revoke-sessions", None),
    ],
)
async def test_unknown_user_returns_404(
    admin_client, test_db, suffix, payload
):
    url = f"{USERS_URL}/{uuid.uuid4()}{suffix}"
    response = (
        admin_client.post(url, json=payload)
        if payload is not None
        else admin_client.post(url)
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"

    for action in ("user.disable", "user.enable", "user.revoke_sessions"):
        assert await _audit_rows(test_db, action) == []


@pytest.mark.parametrize(
    "payload",
    [{}, {"reason": ""}, {"reason": "   "}, {"reason": "x" * 501}],
)
async def test_disable_requires_non_blank_reason(
    admin_client, mock_user, payload
):
    response = admin_client.post(
        f"{USERS_URL}/{mock_user.id}/disable", json=payload
    )
    assert response.status_code == 422


async def test_last_active_admin_cannot_be_deactivated(test_db, admin_user):
    with pytest.raises(admin_auth.LastActiveAdminError):
        await admin_auth.set_admin_active(test_db, admin_user, active=False)

    await test_db.refresh(admin_user)
    assert admin_user.is_active is True

    rows = await _audit_rows(test_db, "admin.deactivate_blocked")
    assert len(rows) == 1
    assert rows[0].details["outcome"] == "failure"
    assert rows[0].details["reason"] == "last_active_admin"


async def test_deactivation_allowed_while_another_admin_active(
    test_db, admin_user
):
    second = AdminUser(
        username="second-admin",
        password_hash=admin_user.password_hash,
        is_active=True,
    )
    test_db.add(second)
    await test_db.commit()
    await test_db.refresh(second)

    await admin_auth.set_admin_active(test_db, second, active=False)
    await test_db.refresh(second)
    assert second.is_active is False

    rows = await _audit_rows(test_db, "admin.deactivated")
    assert len(rows) == 1
    assert rows[0].details["outcome"] == "success"

    # Now admin_user is the last active admin — refused again.
    with pytest.raises(admin_auth.LastActiveAdminError):
        await admin_auth.set_admin_active(test_db, admin_user, active=False)


async def test_deactivation_revokes_admin_sessions(test_db, admin_user):
    second = AdminUser(
        username="session-target",
        password_hash=admin_user.password_hash,
        is_active=True,
    )
    test_db.add(second)
    await test_db.commit()
    await test_db.refresh(second)
    _, _ = await admin_auth.create_admin_session(
        test_db, admin=second, ip_address=None, user_agent=None
    )
    await test_db.commit()

    await admin_auth.set_admin_active(test_db, second, active=False)
    assert await admin_auth.revoke_admin_sessions(test_db, admin=second) == 0
