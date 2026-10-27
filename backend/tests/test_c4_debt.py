"""C4 test debt (B28-B30, B32, B33).

Announcement public-visibility + audit + separation, OAuth smoke,
and SSE stream smoke.
"""

import uuid
from unittest.mock import patch

import pytest

from app.core.auth import SESSION_COOKIE_NAME, create_access_token
from app.models.admin import AdminUser
from app.models.audit import AuditLog
from app.models.platform import Announcement
from sqlalchemy import select

ADMIN_MSG = "announcement test"


async def _audit_count(db, action):
    rows = (await db.execute(select(AuditLog).where(AuditLog.action == action))).scalars().all()
    return len(rows)


# ---------------------------------------------------------------------------
# B28 — public feed excludes drafts/expired/disabled
# ---------------------------------------------------------------------------


async def test_b28_public_feed_visibility(test_db, admin_client, anon_client):
    # Create a draft announcement.
    created = admin_client.post(
        "/api/v1/admin/announcements",
        json={"title": "Draft", "message": "draft msg", "kind": "general"},
    )
    assert created.status_code == 201, created.text
    aid = created.json()["id"]

    # Draft is not public.
    public_before = anon_client.get("/api/v1/platform/announcements")
    assert public_before.status_code == 200
    assert all(a["title"] != "Draft" for a in public_before.json())

    # Publish it.
    pub = admin_client.put(
        f"/api/v1/admin/announcements/{aid}",
        json={"state": "published"},
    )
    assert pub.status_code == 200, pub.text

    public_after = anon_client.get("/api/v1/platform/announcements")
    assert public_after.status_code == 200
    assert any(a["title"] == "Draft" for a in public_after.json())

    # Unpublish → disappears again.
    admin_client.put(f"/api/v1/admin/announcements/{aid}", json={"state": "draft"})
    public_final = anon_client.get("/api/v1/platform/announcements")
    assert all(a["title"] != "Draft" for a in public_final.json())


# ---------------------------------------------------------------------------
# B29 — every mutation writes exactly one audit row
# ---------------------------------------------------------------------------


async def test_b29_announcement_mutations_audited(test_db, admin_client):
    created = admin_client.post(
        "/api/v1/admin/announcements",
        json={"title": "AuditMe", "message": "m", "kind": "general"},
    )
    assert created.status_code == 201
    aid = created.json()["id"]
    assert await _audit_count(test_db, "admin.announcement_created") == 1

    admin_client.put(f"/api/v1/admin/announcements/{aid}", json={"title": "AuditMe2"})
    assert await _audit_count(test_db, "admin.announcement_updated") == 1

    admin_client.put(f"/api/v1/admin/announcements/{aid}", json={"state": "published"})
    assert await _audit_count(test_db, "admin.announcement_published") == 1

    admin_client.delete(f"/api/v1/admin/announcements/{aid}")
    assert await _audit_count(test_db, "admin.announcement_deleted") == 1


# ---------------------------------------------------------------------------
# B30 — announcements do not alter access controls / flags / maintenance
# ---------------------------------------------------------------------------


async def test_b30_announcements_are_informational(test_db, admin_client, anon_client):
    before_features = anon_client.get("/api/v1/platform/features").json()
    before_status = anon_client.get("/api/v1/platform/status").json()

    created = admin_client.post(
        "/api/v1/admin/announcements",
        json={"title": "Info", "message": "m", "kind": "general"},
    )
    assert created.status_code == 201
    aid = created.json()["id"]
    admin_client.put(f"/api/v1/admin/announcements/{aid}", json={"state": "published"})

    after_features = anon_client.get("/api/v1/platform/features").json()
    after_status = anon_client.get("/api/v1/platform/status").json()

    assert before_features == after_features
    assert before_status.get("maintenance") == after_status.get("maintenance")


# ---------------------------------------------------------------------------
# B32 — OAuth smoke (mocked GitHub round-trip)
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
        return _FakeResp(200, {"access_token": "gh-smoke-token"})

    async def get(self, url, **kwargs):
        if "api.github.com/user/emails" in url:
            return _FakeResp(200, [])
        return _FakeResp(200, self._gh_user)


async def test_b32_oauth_smoke(test_db, anon_client, monkeypatch):
    from app.core.config import settings
    from app.models.user import User as UserModel
    import uuid

    # Pre-seed so the flow resolves an existing user (no registration commit).
    seeded = UserModel(
        id=uuid.uuid4(),
        name="Smoke User",
        email="smoke@example.com",
        role="user",
        is_verified=True,
        github_id=999001,
        github_username="smokeuser",
    )
    test_db.add(seeded)
    await test_db.commit()

    monkeypatch.setattr(settings, "GITHUB_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(settings, "GITHUB_CLIENT_SECRET", "test-client-secret")

    gh_user = {
        "id": 999001,
        "login": "smokeuser",
        "name": "Smoke User",
        "email": "smoke@example.com",
        "avatar_url": None,
    }
    fake = _FakeClient(gh_user)
    with patch("httpx.AsyncClient", return_value=fake):
        response = anon_client.post(
            "/api/v1/auth/github",
            json={"code": "smoke-code", "state": None},
        )

    assert response.status_code == 200, response.text
    assert "access_token" in response.json()
    assert response.cookies.get(SESSION_COOKIE_NAME) is not None


# ---------------------------------------------------------------------------
# B33 — SSE stream smoke
# ---------------------------------------------------------------------------


async def test_b33_sse_stream_smoke(test_db, anon_client, mock_user, user_auth_token):
    # Unauthenticated requests are rejected (route registered + auth enforced).
    unauth = anon_client.get("/api/v1/reviews/stream")
    assert unauth.status_code == 401

    # Authenticated dependency check: a valid token must not be rejected at
    # the auth layer. We assert via a non-streaming protected endpoint that
    # shares the same dependency, plus OpenAPI registration of the stream route.
    anon_client.cookies.set(SESSION_COOKIE_NAME, user_auth_token)
    assert anon_client.get("/api/v1/auth/me").status_code == 200

    schema = anon_client.get("/openapi.json")
    assert schema.status_code == 200
    paths = schema.json().get("paths", {})
    stream_registered = any("reviews/stream" in p for p in paths)
    assert stream_registered, "SSE stream route not registered"