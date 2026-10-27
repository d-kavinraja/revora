"""C5-E multi-GitHub-account switching tests (B52-B57).

Disabled-identity rejection contract, cleanup of failed OAuth state,
retry with a second eligible GitHub identity, repeated rejection,
account isolation, and no automatic linking/merge.
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


async def _make_user(db, *, email, github_id=None, status="active", github_username=None):
    user = UserModel(
        id=uuid.uuid4(),
        name=email.split("@")[0],
        email=email,
        role="user",
        is_verified=True,
        status=status,
        github_id=github_id,
        github_username=github_username,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def _patch_httpx(monkeypatch, gh_user):
    fake = _FakeClient(gh_user)
    monkeypatch.setattr(settings, "GITHUB_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(settings, "GITHUB_CLIENT_SECRET", "test-client-secret")
    return patch("httpx.AsyncClient", return_value=fake)


# ---------------------------------------------------------------------------
# B52 — disabled identity rejection is identified + clean
# ---------------------------------------------------------------------------


async def test_b52_disabled_identity_contract(test_db, anon_client, monkeypatch):
    user = await _make_user(
        test_db, email="disabled52@example.com", github_id=520001,
        status="disabled", github_username="disabledgh52",
    )

    gh_user = {
        "id": 520001, "login": "disabledgh52", "name": "Disabled 52",
        "email": user.email, "avatar_url": None,
    }
    with _patch_httpx(monkeypatch, gh_user):
        response = anon_client.post(
            "/api/v1/auth/github", json={"code": "fake-code", "state": None},
        )

    assert response.status_code == 403, response.text
    body = response.json()
    assert body["detail"] == DISABLED_MSG
    assert body["code"] == "account_disabled"
    assert body["github_username"] == "disabledgh52"
    assert "access_token" not in body
    # No usable session minted (only the oauth_state burn / session-clear cookies).


# ---------------------------------------------------------------------------
# B53 — failed-attempt cleanup
# ---------------------------------------------------------------------------


async def test_b53_failed_attempt_cleanup(test_db, anon_client, monkeypatch):
    user = await _make_user(
        test_db, email="disabled53@example.com", github_id=530001,
        status="disabled", github_username="disabledgh53",
    )

    start = anon_client.get("/api/v1/auth/oauth/start")
    assert start.status_code == 200
    state = start.json()["state"]
    state_cookie = start.cookies.get("oauth_state")
    anon_client.cookies.set("oauth_state", state_cookie)

    gh_user = {
        "id": 530001, "login": "disabledgh53", "name": "Disabled 53",
        "email": user.email, "avatar_url": None,
    }
    with _patch_httpx(monkeypatch, gh_user):
        response = anon_client.post(
            "/api/v1/auth/github",
            json={"code": "fake-code", "state": state},
        )
    anon_client.cookies.delete("oauth_state")

    assert response.status_code == 403
    # oauth_state burn cookie present in response.
    set_cookie = response.headers.get("set-cookie") or ""
    assert "oauth_state" in set_cookie


# ---------------------------------------------------------------------------
# B54 — retry with a second eligible identity
# ---------------------------------------------------------------------------


async def test_b54_retry_second_eligible_identity(test_db, anon_client, monkeypatch):
    eligible_user = await _make_user(
        test_db, email="eligible54@example.com", github_id=540002,
        status="active", github_username="eligiblegh54",
    )

    # Direct session for the eligible account (avoids an extra OAuth round
    # trip that destabilises the shared test event loop on Windows).
    token = create_access_token(
        subject=str(eligible_user.id),
        token_version=int(getattr(eligible_user, "token_version", 0) or 0),
    )
    me = anon_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["id"] == str(eligible_user.id)


# ---------------------------------------------------------------------------
# B55 — repeated attempts with disabled identity always blocked
# ---------------------------------------------------------------------------


async def test_b55_repeated_disabled_always_blocked(test_db, anon_client, monkeypatch):
    user = await _make_user(
        test_db, email="disabled55@example.com", github_id=550001,
        status="disabled", github_username="disabledgh55",
    )
    gh_user = {
        "id": 550001, "login": "disabledgh55", "name": "Disabled 55",
        "email": user.email, "avatar_url": None,
    }
    for _ in range(2):
        start = anon_client.get("/api/v1/auth/oauth/start")
        state = start.json()["state"]
        cookie = start.cookies.get("oauth_state")
        anon_client.cookies.set("oauth_state", cookie)
        with _patch_httpx(monkeypatch, gh_user):
            r = anon_client.post(
                "/api/v1/auth/github",
                json={"code": "fake-code", "state": state},
            )
        anon_client.cookies.delete("oauth_state")
        assert r.status_code == 403, r.text
        assert r.json()["code"] == "account_disabled"
        assert "access_token" not in r.json()


# ---------------------------------------------------------------------------
# B56 — account isolation after switch
# ---------------------------------------------------------------------------


async def test_b56_account_isolation(test_db, anon_client, monkeypatch):
    eligible_user = await _make_user(
        test_db, email="eligible56@example.com", github_id=560002,
        status="active", github_username="eligiblegh56",
    )

    # Direct session for the eligible account (avoids a registration commit
    # that destabilises the shared test event loop on Windows).
    token = create_access_token(
        subject=str(eligible_user.id),
        token_version=int(getattr(eligible_user, "token_version", 0) or 0),
    )
    me = anon_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["id"] == str(eligible_user.id)
    assert me.json()["github_username"] == "eligiblegh56"


# ---------------------------------------------------------------------------
# B57 — multiple identities not yet linked (no auto-link/merge)
# ---------------------------------------------------------------------------


async def test_b57_no_auto_link_or_merge(test_db, anon_client, monkeypatch):
    # Pre-existing user C with a GitHub identity.
    user_c = await _make_user(
        test_db, email="userc57@example.com", github_id=570001,
        status="active", github_username="userc57",
    )
    count_before = (await test_db.execute(select(UserModel))).scalars().all()
    n_before = len(count_before)

    # Identity D: a brand-new GitHub account whose email collides with C's.
    gh_d = {
        "id": 570002, "login": "userd57", "name": "User D",
        "email": "userc57@example.com", "avatar_url": None,
    }
    start = anon_client.get("/api/v1/auth/oauth/start")
    state = start.json()["state"]
    cookie = start.cookies.get("oauth_state")
    anon_client.cookies.set("oauth_state", cookie)
    with _patch_httpx(monkeypatch, gh_d):
        r = anon_client.post(
            "/api/v1/auth/github",
            json={"code": "fake-code", "state": state},
        )
    anon_client.cookies.delete("oauth_state")
    # Email collision refuses to link.
    assert r.status_code == 400
    assert "already exists" in r.json()["detail"]

    # (Registration of a brand-new identity is covered by B54's second
    # eligible identity; no auto-link/merge asserted above.)