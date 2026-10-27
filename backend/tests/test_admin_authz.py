"""Phase 1 admin authz acceptance tests (plan §22 subset B1-B9).

Every request runs through the REAL auth dependencies via `anon_client` /
`admin_client` (the regular `client` fixture overrides `get_current_user`
and would mask cross-namespace isolation). Coverage:

- B1: every `/api/v1/admin/*` route 401s without a session; blanket check
  that every admin route declares `get_current_admin`.
- B2: user JWT cannot authenticate the admin namespace.
- B3: admin cookie cannot authenticate user routes.
- B4: tampered / expired / revoked / inactive-admin / deleted-admin -> 401.
- B5: generic, identical credential errors (no enumeration).
- B6: lockout after 5 failures; correct password also 429 while locked;
  window reset restores login.
- B7: hash-only session storage, HttpOnly cookie, audit row without secrets.
- B8: attacker-supplied cookie value is never honored or retained.
- B9: password rotation revokes existing sessions.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.core.deps_admin import (
    ADMIN_SESSION_COOKIE,
    get_current_admin,
    hash_admin_token,
)
from app.main import app
from app.middleware.rate_limit import limiter
from app.models.admin import AdminSession, AdminUser
from app.models.audit import AuditLog
from app.services import admin_auth

LOGIN_URL = "/api/v1/admin/auth/login"
SESSION_URL = "/api/v1/admin/auth/session"
LOGOUT_URL = "/api/v1/admin/auth/logout"
ADMIN_PASSWORD = "admin-test-password"


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    """Keep the per-IP login limiter from bleeding across tests.

    The 5/minute login limit and the service lockout share the 429 status
    but not the message; tests assert which one fired.
    """
    limiter.reset()
    yield
    limiter.reset()


def _admin_route_methods(include_public: bool = False) -> list[tuple[str, str]]:
    routes = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/v1/admin/"):
            continue
        if not include_public and path == LOGIN_URL:
            continue
        for method in sorted(getattr(route, "methods", set())):
            routes.append((method, path))
    return routes


def _dependency_calls(dependant) -> set:
    found = set()
    for sub in getattr(dependant, "dependencies", []):
        if sub.call is not None:
            found.add(sub.call)
        found |= _dependency_calls(sub)
    return found


async def _session_row(test_db, raw_token: str) -> AdminSession:
    result = await test_db.execute(
        select(AdminSession).where(
            AdminSession.token_hash == hash_admin_token(raw_token)
        )
    )
    return result.scalars().first()


def _login(client, password: str = ADMIN_PASSWORD, username: str = "testadmin"):
    return client.post(
        LOGIN_URL, json={"username": username, "password": password}
    )


# ---------------------------------------------------------------------------
# B1 - anonymous access
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method,path", _admin_route_methods())
def test_b1_admin_routes_reject_anonymous(anon_client, method, path):
    response = anon_client.request(method, path)
    assert response.status_code == 401, (method, path, response.text)


def test_b1b_every_admin_route_declares_admin_dependency():
    """Blanket guard: any future /admin route missing get_current_admin fails."""
    missing = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/v1/admin/") or path == LOGIN_URL:
            continue
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            continue
        if get_current_admin not in _dependency_calls(dependant):
            missing.append(path)
    assert missing == []


# ---------------------------------------------------------------------------
# B2 / B3 - namespace isolation
# ---------------------------------------------------------------------------


def test_b2_user_token_cannot_authenticate_admin_namespace(
    anon_client, user_auth_token
):
    response = anon_client.get(
        SESSION_URL, headers={"Authorization": f"Bearer {user_auth_token}"}
    )
    assert response.status_code == 401


def test_b3_admin_cookie_cannot_authenticate_user_routes(admin_client):
    assert admin_client.get("/api/v1/auth/me").status_code == 401


# ---------------------------------------------------------------------------
# B4 - invalid sessions
# ---------------------------------------------------------------------------


def test_b4_tampered_token_rejected(anon_client, admin_session_cookie):
    anon_client.cookies.set(ADMIN_SESSION_COOKIE, admin_session_cookie + "tamper")
    assert anon_client.get(SESSION_URL).status_code == 401


async def test_b4_expired_session_rejected(
    admin_client, test_db, admin_session_cookie
):
    row = await _session_row(test_db, admin_session_cookie)
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    test_db.add(row)
    await test_db.commit()
    assert admin_client.get(SESSION_URL).status_code == 401


async def test_b4_revoked_session_rejected(
    admin_client, test_db, admin_session_cookie
):
    row = await _session_row(test_db, admin_session_cookie)
    row.revoked_at = datetime.now(UTC)
    test_db.add(row)
    await test_db.commit()
    assert admin_client.get(SESSION_URL).status_code == 401


async def test_b4_inactive_admin_rejected(admin_client, test_db, admin_user):
    admin_user.is_active = False
    test_db.add(admin_user)
    await test_db.commit()
    assert admin_client.get(SESSION_URL).status_code == 401


async def test_b4_deleted_admin_rejected(admin_client, test_db, admin_user):
    await test_db.execute(delete(AdminUser).where(AdminUser.id == admin_user.id))
    await test_db.commit()
    assert admin_client.get(SESSION_URL).status_code == 401


# ---------------------------------------------------------------------------
# B5 - generic credential errors
# ---------------------------------------------------------------------------


async def test_b5_credential_errors_are_generic_and_identical(
    anon_client, test_db, admin_user
):
    retired = AdminUser(
        username="retired-admin",
        password_hash=admin_user.password_hash,
        is_active=False,
    )
    test_db.add(retired)
    await test_db.commit()

    bodies = set()
    for username, password in [
        ("testadmin", "wrong-password"),
        ("ghost-admin", "wrong-password"),
        ("retired-admin", ADMIN_PASSWORD),
    ]:
        limiter.reset()
        response = _login(anon_client, password=password, username=username)
        assert response.status_code == 401, username
        bodies.add(response.text)

    assert len(bodies) == 1
    assert "invalid credentials" in bodies.pop().lower()


async def test_b5_lockout_is_not_an_existence_oracle(
    anon_client, test_db, admin_user
):
    """B5 extension: repeated failures must not reveal whether a username
    exists. An unknown username and a real one must yield identical
    status codes and bodies, including across the lockout threshold."""

    def _five_wrong(username: str) -> set[tuple[int, str]]:
        results = set()
        for _ in range(5):
            limiter.reset()
            response = _login(anon_client, username=username, password="wrong")
            results.add((response.status_code, response.text))
        return results

    existing = _five_wrong("testadmin")
    await test_db.refresh(admin_user)
    assert admin_auth.is_admin_locked(admin_user)

    unknown = _five_wrong("ghost-admin")

    assert existing == unknown
    assert {status for status, _ in existing} == {401}


# ---------------------------------------------------------------------------
# B6 - lockout
# ---------------------------------------------------------------------------


async def test_b6_lockout_after_five_failures(anon_client, test_db, admin_user):
    for attempt in range(4):
        limiter.reset()
        response = _login(anon_client, password="wrong-password")
        assert response.status_code == 401, f"attempt {attempt + 1}"

    # Fifth consecutive failure engages the lock, but the response stays a
    # generic 401 so an unauthenticated caller cannot detect the lock (or the
    # account's existence) from the status code.
    limiter.reset()
    fifth = _login(anon_client, password="wrong-password")
    assert fifth.status_code == 401
    assert "invalid credentials" in fifth.json()["detail"].lower()

    await test_db.refresh(admin_user)
    assert admin_user.locked_until is not None
    assert admin_auth.is_admin_locked(admin_user)
    locked_until = admin_user.locked_until

    # Further wrong attempts must NOT extend the lock window (DoS guard).
    limiter.reset()
    still_locked = _login(anon_client, password="wrong-password")
    assert still_locked.status_code == 401
    await test_db.refresh(admin_user)
    assert admin_user.locked_until == locked_until

    # The correct password alone reveals the lock (429) — only reachable by a
    # caller who already knows the credential, so it is not an oracle.
    limiter.reset()
    while_locked = _login(anon_client)
    assert while_locked.status_code == 429
    assert "too many failed attempts" in while_locked.json()["detail"].lower()

    lock_audits = (
        (
            await test_db.execute(
                select(AuditLog).where(AuditLog.action == "admin.login_locked")
            )
        )
        .scalars()
        .all()
    )
    assert len(lock_audits) >= 2

    # Window passes: correct password logs in and resets the counter.
    admin_user.locked_until = datetime.now(UTC) - timedelta(seconds=1)
    test_db.add(admin_user)
    await test_db.commit()

    limiter.reset()
    success = _login(anon_client)
    assert success.status_code == 200

    await test_db.refresh(admin_user)
    assert admin_user.failed_login_count == 0
    assert admin_user.locked_until is None


# ---------------------------------------------------------------------------
# B7 - hash-only storage, HttpOnly cookie, audit
# ---------------------------------------------------------------------------


async def test_b7_login_persists_hash_only_and_audits(
    anon_client, test_db, admin_user
):
    response = _login(anon_client)
    assert response.status_code == 200

    raw = response.cookies.get(ADMIN_SESSION_COOKIE)
    assert raw
    assert "httponly" in response.headers.get("set-cookie", "").lower()
    assert raw not in response.text

    sessions = (await test_db.execute(select(AdminSession))).scalars().all()
    assert len(sessions) == 1
    assert sessions[0].token_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert sessions[0].token_hash != raw

    audits = (
        (
            await test_db.execute(
                select(AuditLog).where(AuditLog.action == "admin.login_success")
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1
    serialized = str(audits[0].details) + str(audits[0].actor_id)
    assert raw not in serialized
    assert "password" not in serialized.lower()


async def test_session_endpoint_shape(admin_client):
    response = admin_client.get(SESSION_URL)
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "testadmin"
    assert datetime.fromisoformat(body["expires_at"])


async def test_logout_revokes_session(admin_client, test_db, admin_session_cookie):
    assert admin_client.get(SESSION_URL).status_code == 200
    assert admin_client.post(LOGOUT_URL).status_code == 200
    assert admin_client.get(SESSION_URL).status_code == 401

    row = await _session_row(test_db, admin_session_cookie)
    assert row is not None and row.revoked_at is not None

    audits = (
        (
            await test_db.execute(
                select(AuditLog).where(AuditLog.action == "admin.logout")
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1


# ---------------------------------------------------------------------------
# B8 - session fixation
# ---------------------------------------------------------------------------


async def test_b8_attacker_supplied_cookie_never_honored(
    anon_client, test_db, admin_user
):
    attacker_token = secrets.token_urlsafe(32)
    anon_client.cookies.set(ADMIN_SESSION_COOKIE, attacker_token)
    assert anon_client.get(SESSION_URL).status_code == 401

    response = _login(anon_client)
    assert response.status_code == 200
    raw = response.cookies.get(ADMIN_SESSION_COOKIE)
    assert raw and raw != attacker_token

    sessions = (await test_db.execute(select(AdminSession))).scalars().all()
    assert [s.token_hash for s in sessions] == [hash_admin_token(raw)]

    # The planted value never authenticates; the server-minted one does.
    anon_client.cookies.clear()
    anon_client.cookies.set(ADMIN_SESSION_COOKIE, attacker_token)
    assert anon_client.get(SESSION_URL).status_code == 401
    anon_client.cookies.clear()
    anon_client.cookies.set(ADMIN_SESSION_COOKIE, raw)
    assert anon_client.get(SESSION_URL).status_code == 200


# ---------------------------------------------------------------------------
# B9 - password rotation revokes sessions
# ---------------------------------------------------------------------------


async def test_b9_password_rotation_revokes_sessions(
    admin_client, test_db, admin_user
):
    assert admin_client.get(SESSION_URL).status_code == 200

    await admin_auth.set_admin_password(test_db, admin_user, "rotated-password-1")

    assert admin_client.get(SESSION_URL).status_code == 401

    limiter.reset()
    stale = _login(admin_client, password=ADMIN_PASSWORD)
    assert stale.status_code == 401

    limiter.reset()
    fresh = _login(admin_client, password="rotated-password-1")
    assert fresh.status_code == 200
