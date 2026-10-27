"""OAuth callback replay/refresh contract for GitHub sign-in.

A GitHub authorization code is single-use. Refreshing (or otherwise
re-entering) the callback page must never exchange the same code twice, and a
replayed/expired code must produce an honest, recoverable error rather than a
credential-blaming one or a false session.

Covers: fresh-login success + durable session, code replay after consumption,
client-credential misconfiguration reported as a config problem (env var names
only, never values), redirect-URI mismatch, invalid state rejection, and the
"failed exchange never mints a session" invariant.
"""

import pytest
from unittest.mock import patch

from app.core.auth import SESSION_COOKIE_NAME
from app.core.config import settings


@pytest.fixture(autouse=True)
def _no_login_reconciliation(monkeypatch):
    """Neutralize the post-login background task for these tests.

    A successful exchange schedules `_login_reconciliation`, which opens its own
    `AsyncSessionLocal` against the REAL database (not the test's overridden
    session). Those tasks outlive the test that created them and then fail on a
    closed event loop, breaking whichever test happens to run next.
    """

    async def _noop(user_id):  # pragma: no cover - background task stand-in
        return None

    monkeypatch.setattr(
        "app.api.v1.endpoints.auth._login_reconciliation", _noop, raising=True
    )


GH_USER = {
    "id": 880001,
    "login": "replayuser",
    "name": "Replay User",
    "email": "replay-user@example.com",
    "avatar_url": None,
}

# GitHub's real response when a code is re-presented (or has expired).
REPLAY_RESPONSE = {
    "error": "bad_verification_code",
    "error_description": "The code passed is incorrect or expired.",
}
# GitHub's real response when client_id/client_secret are wrong.
BAD_CREDENTIALS_RESPONSE = {
    "error": "incorrect_client_credentials",
    "error_description": "The client_id and/or client_secret passed are incorrect.",
}
# GitHub's real response when redirect_uri is not registered for the app.
REDIRECT_MISMATCH_RESPONSE = {
    "error": "redirect_uri_mismatch",
    "error_description": "The redirect_uri MUST match the registered URL for this application.",
}


class _FakeResp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def is_success(self):
        return self.status_code < 400

    def json(self):
        return self._payload


class _FakeClient:
    """Scripted GitHub token-endpoint responses, fixed profile endpoint."""

    def __init__(self, token_responses=None, gh_user=None):
        self._token_responses = list(token_responses or [])
        self._gh_user = gh_user or GH_USER

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        if self._token_responses:
            return self._token_responses.pop(0)
        return _FakeResp(200, {"access_token": "gh-test-token"})

    async def get(self, url, **kwargs):
        if "api.github.com/user/emails" in url:
            return _FakeResp(200, [])
        return _FakeResp(200, self._gh_user)


def _patch_httpx(monkeypatch, fake):
    monkeypatch.setattr(settings, "GITHUB_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(settings, "GITHUB_CLIENT_SECRET", "test-client-secret")
    return patch("httpx.AsyncClient", return_value=fake)


# ---------------------------------------------------------------------------
# Fresh login succeeds and the session survives repeated reads (reload-safe)
# ---------------------------------------------------------------------------


async def test_oauth_fresh_login_success_establishes_valid_session(
    test_db, anon_client, monkeypatch
):
    fake = _FakeClient([_FakeResp(200, {"access_token": "gh-test-token"})])
    with _patch_httpx(monkeypatch, fake):
        response = anon_client.post(
            "/api/v1/auth/github", json={"code": "fresh-code", "state": None}
        )

    assert response.status_code == 200, response.text
    assert "access_token" in response.json()

    session = response.cookies.get(SESSION_COOKIE_NAME)
    assert session, "backend must set the HttpOnly session cookie"

    # The durable session survives repeated reads — this is what makes a page
    # refresh restore the existing session instead of restarting OAuth.
    anon_client.cookies.set(SESSION_COOKIE_NAME, session)
    assert anon_client.get("/api/v1/auth/me").status_code == 200
    assert anon_client.get("/api/v1/auth/me").status_code == 200


# ---------------------------------------------------------------------------
# Replay of an already-consumed code: honest error, never a false session
# ---------------------------------------------------------------------------


async def test_replayed_code_is_rejected_without_false_session(
    test_db, anon_client, monkeypatch
):
    fake = _FakeClient(
        [
            _FakeResp(200, {"access_token": "gh-test-token"}),
            _FakeResp(200, dict(REPLAY_RESPONSE)),
            _FakeResp(200, dict(REPLAY_RESPONSE)),
        ]
    )
    with _patch_httpx(monkeypatch, fake):
        first = anon_client.post(
            "/api/v1/auth/github", json={"code": "one-shot", "state": None}
        )
        assert first.status_code == 200, first.text
        assert first.cookies.get(SESSION_COOKIE_NAME)

        # Simulate the browser coming back with the same consumed code.
        anon_client.cookies.clear()
        replay = anon_client.post(
            "/api/v1/auth/github", json={"code": "one-shot", "state": None}
        )

    assert replay.status_code == 400, replay.text
    body = replay.json()
    assert body["code"] == "oauth_code_invalid"
    assert "already been used" in body["detail"]
    # The old message blamed credentials; a replay must not do that.
    assert "GITHUB_CLIENT_SECRET" not in body["detail"]
    assert "GITHUB_CLIENT_ID" not in body["detail"]
    # No false login: no token, no session cookie.
    assert "access_token" not in body
    assert SESSION_COOKIE_NAME not in replay.cookies


# ---------------------------------------------------------------------------
# Credential misconfiguration is reported as a config problem, without secrets
# ---------------------------------------------------------------------------


async def test_client_credentials_mismatch_reports_config_error(
    test_db, anon_client, monkeypatch
):
    fake = _FakeClient([_FakeResp(200, dict(BAD_CREDENTIALS_RESPONSE))])
    with _patch_httpx(monkeypatch, fake):
        response = anon_client.post(
            "/api/v1/auth/github", json={"code": "any-code", "state": None}
        )

    assert response.status_code == 500, response.text
    body = response.json()
    assert body["code"] == "oauth_config_error"
    assert "GITHUB_CLIENT_ID" in body["detail"]
    assert "GITHUB_CLIENT_SECRET" in body["detail"]
    # Diagnostic must name the variables without leaking their values.
    assert "test-client-id" not in response.text
    assert "test-client-secret" not in response.text
    assert "access_token" not in body
    assert SESSION_COOKIE_NAME not in response.cookies


# ---------------------------------------------------------------------------
# redirect_uri mismatch is called out separately from credential problems
# ---------------------------------------------------------------------------


async def test_redirect_uri_mismatch_reports_redirect_error(
    test_db, anon_client, monkeypatch
):
    fake = _FakeClient([_FakeResp(200, dict(REDIRECT_MISMATCH_RESPONSE))])
    with _patch_httpx(monkeypatch, fake):
        response = anon_client.post(
            "/api/v1/auth/github", json={"code": "any-code", "state": None}
        )

    assert response.status_code == 400, response.text
    body = response.json()
    assert body["code"] == "oauth_redirect_mismatch"
    assert "redirect URL" in body["detail"]
    assert "access_token" not in body
    assert SESSION_COOKIE_NAME not in response.cookies


# ---------------------------------------------------------------------------
# Invalid / mismatched state is still rejected when state is mandatory
# ---------------------------------------------------------------------------


async def test_invalid_state_is_rejected(test_db, anon_client, monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "GITHUB_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(settings, "GITHUB_CLIENT_SECRET", "test-client-secret")

    anon_client.cookies.set("oauth_state", "the-real-stored-state")

    # No GitHub exchange must be attempted at all: the flow is refused before
    # the single-use code is ever sent upstream.
    fake = _FakeClient()
    with patch("httpx.AsyncClient", return_value=fake):
        response = anon_client.post(
            "/api/v1/auth/github",
            json={"code": "some-code", "state": "a-different-state"},
        )

    assert response.status_code == 400, response.text
    assert "login session" in response.json()["detail"]
    assert SESSION_COOKIE_NAME not in response.cookies


async def test_missing_state_is_rejected(test_db, anon_client, monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "GITHUB_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(settings, "GITHUB_CLIENT_SECRET", "test-client-secret")

    anon_client.cookies.delete("oauth_state", path="/")

    fake = _FakeClient()
    with patch("httpx.AsyncClient", return_value=fake):
        response = anon_client.post(
            "/api/v1/auth/github", json={"code": "some-code"}
        )

    assert response.status_code == 400, response.text
    assert "login session" in response.json()["detail"]
    assert SESSION_COOKIE_NAME not in response.cookies
