"""C5 disabled-user enforcement tests (B41-B51).

Server-side gate (password + GitHub), existing-session rejection,
restore flow, data preservation and regression coverage.
"""

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.auth import SESSION_COOKIE_NAME, create_access_token, get_password_hash
from app.core.config import settings
from app.models.api_key import ApiKey
from app.models.github import Installation, Repository
from app.models.user import User as UserModel

DISABLED_MSG = "Your account has been disabled. Please contact the administrator for assistance."


async def _seed_key(db, user):
    key = ApiKey(
        user_id=user.id,
        provider="openai",
        label="Primary",
        encrypted_key=__import__("app.core.security", fromlist=["encryption_service"]).encryption_service.encrypt("sk-test"),
        is_valid=True,
        is_enabled=True,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return key


async def _seed_repo(db, user):
    installation = Installation(
        installation_id=99099,
        account_id=9999,
        account_login="acct",
        account_type="User",
        user_id=user.id,
        repository_selection="all",
        permissions={},
        events={},
    )
    db.add(installation)
    await db.commit()
    await db.refresh(installation)
    repo = Repository(
        github_id=99099,
        name="disabled-user-repo",
        full_name="acct/disabled-user-repo",
        installation_id=installation.id,
        reviews_enabled=True,
        settings={},
    )
    db.add(repo)
    await db.commit()
    await db.refresh(repo)
    return repo


# ---------------------------------------------------------------------------
# B41 — enabled baseline
# ---------------------------------------------------------------------------


async def test_b41_enabled_user_can_access_me(test_db, anon_client, mock_user, user_auth_token):
    anon_client.cookies.set(SESSION_COOKIE_NAME, user_auth_token)
    response = anon_client.get("/api/v1/auth/me")
    assert response.status_code == 200, response.text


# ---------------------------------------------------------------------------
# B42 — disable blocks next request (cookie + bearer), 403 distinct
# ---------------------------------------------------------------------------


async def test_b42_disable_blocks_cookie_and_bearer(test_db, admin_client, admin_user, mock_user, user_auth_token, anon_client):
    disable = admin_client.post(
        f"/api/v1/admin/users/{mock_user.id}/disable", json={"reason": "abuse"}
    )
    assert disable.status_code == 200, disable.text

    # cookie path
    anon_client.cookies.set(SESSION_COOKIE_NAME, user_auth_token)
    cookie_resp = anon_client.get("/api/v1/auth/me")
    assert cookie_resp.status_code == 403, cookie_resp.text
    assert cookie_resp.json()["detail"] == "Account disabled"

    # bearer path
    bearer_resp = anon_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {user_auth_token}"}
    )
    assert bearer_resp.status_code == 403, bearer_resp.text

    # SSE new stream rejected
    stream_resp = anon_client.get(
        "/api/v1/reviews/stream", headers={"Authorization": f"Bearer {user_auth_token}"}
    )
    assert stream_resp.status_code == 403, stream_resp.text


# ---------------------------------------------------------------------------
# B43 — old token dead after re-enable; fresh token works
# ---------------------------------------------------------------------------


async def test_b43_reenable_requires_fresh_token(test_db, admin_client, admin_user, mock_user, user_auth_token, anon_client):
    admin_client.post(f"/api/v1/admin/users/{mock_user.id}/disable", json={"reason": "abuse"})
    admin_client.post(f"/api/v1/admin/users/{mock_user.id}/enable")

    anon_client.cookies.set(SESSION_COOKIE_NAME, user_auth_token)
    assert anon_client.get("/api/v1/auth/me").status_code == 401

    await test_db.refresh(mock_user)
    fresh = create_access_token(
        subject=str(mock_user.id),
        token_version=int(mock_user.token_version),
    )
    anon_client.cookies.set(SESSION_COOKIE_NAME, fresh)
    assert anon_client.get("/api/v1/auth/me").status_code == 200


# ---------------------------------------------------------------------------
# B44 — password login refuses disabled account before issuing session
# ---------------------------------------------------------------------------


async def test_b44_password_login_disabled(test_db, anon_client, mock_user):
    mock_user.password_hash = get_password_hash("secret-pass")
    mock_user.status = "disabled"
    test_db.add(mock_user)
    await test_db.commit()

    response = anon_client.post(
        "/api/v1/auth/login",
        data={"username": mock_user.email, "password": "secret-pass"},
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == DISABLED_MSG
    assert "access_token" not in response.json()
    assert response.cookies.get(SESSION_COOKIE_NAME) is None

    # Re-enable → login succeeds.
    mock_user.status = "active"
    test_db.add(mock_user)
    await test_db.commit()

    ok = anon_client.post(
        "/api/v1/auth/login",
        data={"username": mock_user.email, "password": "secret-pass"},
    )
    assert ok.status_code == 200, ok.text
    assert "access_token" in ok.json()
    assert ok.cookies.get(SESSION_COOKIE_NAME) is not None


# ---------------------------------------------------------------------------
# B45 — GitHub callback refuses disabled account
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def is_success(self):
        return self.status_code < 400

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, gh_user):
        self._gh_user = gh_user

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        return _FakeResp(200, {"access_token": "gh-test-token"})

    async def get(self, url, **kwargs):
        if "api.github.com/user/emails" in url:
            return _FakeResp(200, [])
        return _FakeResp(200, self._gh_user)


async def test_b45_github_login_disabled(test_db, anon_client, mock_user, monkeypatch):
    # Pre-existing disabled user linked to a GitHub identity.
    mock_user.github_id = 777001
    mock_user.status = "disabled"
    test_db.add(mock_user)
    await test_db.commit()

    monkeypatch.setattr(settings, "GITHUB_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(settings, "GITHUB_CLIENT_SECRET", "test-client-secret")

    gh_user = {
        "id": 777001,
        "login": "disabledgh",
        "name": "Disabled GH",
        "email": mock_user.email,
        "avatar_url": None,
    }
    fake = _FakeClient(gh_user)
    with patch("httpx.AsyncClient", return_value=fake):
        response = anon_client.post(
            "/api/v1/auth/github",
            json={"code": "fake-code", "state": None},
        )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == DISABLED_MSG
    assert "access_token" not in response.json()


# ---------------------------------------------------------------------------
# B46 — rejected auth scan (no usable session remains)
# ---------------------------------------------------------------------------


async def test_b46_no_usable_session_after_disable(test_db, admin_client, admin_user, mock_user, user_auth_token, anon_client):
    admin_client.post(f"/api/v1/admin/users/{mock_user.id}/disable", json={"reason": "abuse"})
    # Both cookie and bearer are rejected.
    anon_client.cookies.set(SESSION_COOKIE_NAME, user_auth_token)
    assert anon_client.get("/api/v1/auth/me").status_code == 403
    assert anon_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {user_auth_token}"}
    ).status_code == 403


# ---------------------------------------------------------------------------
# B47 — data preservation (disable ≠ delete)
# ---------------------------------------------------------------------------


async def test_b47_data_preserved_on_disable(test_db, admin_client, admin_user, mock_user):
    key = await _seed_key(test_db, mock_user)
    repo = await _seed_repo(test_db, mock_user)

    admin_client.post(f"/api/v1/admin/users/{mock_user.id}/disable", json={"reason": "abuse"})

    await test_db.refresh(mock_user)
    assert mock_user.status == "disabled"

    # Keys and repos survive.
    keys = (await test_db.execute(select(ApiKey).where(ApiKey.user_id == mock_user.id))).scalars().all()
    repos = (await test_db.execute(select(Repository).where(Repository.id == repo.id))).scalars().all()
    assert len(keys) == 1 and keys[0].id == key.id
    assert len(repos) == 1


# ---------------------------------------------------------------------------
# B48 — admin authz unchanged
# ---------------------------------------------------------------------------


async def test_b48_admin_unaffected_by_user_disable(test_db, admin_client, admin_user, mock_user):
    admin_client.post(f"/api/v1/admin/users/{mock_user.id}/disable", json={"reason": "abuse"})
    response = admin_client.get("/api/v1/admin/users")
    assert response.status_code == 200, response.text


# ---------------------------------------------------------------------------
# B51 — /auth/me 403 server-side proof (mid-session disable)
# ---------------------------------------------------------------------------


async def test_b51_me_returns_403_after_mid_session_disable(test_db, admin_client, admin_user, mock_user, user_auth_token, anon_client):
    anon_client.cookies.set(SESSION_COOKIE_NAME, user_auth_token)
    assert anon_client.get("/api/v1/auth/me").status_code == 200

    admin_client.post(f"/api/v1/admin/users/{mock_user.id}/disable", json={"reason": "abuse"})

    blocked = anon_client.get("/api/v1/auth/me")
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "Account disabled"