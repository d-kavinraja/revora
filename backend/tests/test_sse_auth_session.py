"""Regression tests for SSE authentication session lifetime.

Production incident: long-lived SSE streams authenticated via a yield-based
``get_current_user`` dependency pinned a pooled PostgreSQL connection for the
entire stream lifetime, starving the in-process review worker.

These tests prove the new ``get_current_user_for_stream`` helper releases its
database session before the StreamingResponse starts.
"""

import contextlib
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

import app.core.deps as deps_mod
from app.core.deps import get_current_user_for_stream, get_db
from app.main import app


@pytest.fixture
def stream_client(test_db, mock_user):
    """TestClient with real (non-overridden) SSE auth, backed by test_db."""

    @contextlib.asynccontextmanager
    async def _factory() -> AsyncIterator[AsyncSession]:
        yield test_db

    original_factory = deps_mod.stream_auth_session_factory
    deps_mod.stream_auth_session_factory = lambda: _factory()

    async def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()
    deps_mod.stream_auth_session_factory = original_factory


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_sse_auth_http_rejects_missing_token(stream_client):
    resp = stream_client.get("/api/v1/reviews/stream")
    assert resp.status_code == 401


def test_sse_auth_http_rejects_invalid_token(stream_client):
    resp = stream_client.get(
        "/api/v1/reviews/stream", headers={"Authorization": "Bearer not-a-token"}
    )
    assert resp.status_code == 401


async def test_sse_auth_http_rejects_disabled_user(stream_client, mock_user, user_auth_token, test_db):
    mock_user.status = "disabled"
    test_db.add(mock_user)
    await test_db.commit()
    resp = stream_client.get(
        "/api/v1/reviews/stream", headers=_bearer(user_auth_token)
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Account disabled"


async def test_sse_auth_helper_succeeds_for_valid_user(test_db, mock_user, user_auth_token):
    """The auth helper authenticates a valid user and returns it."""
    deps_mod.stream_auth_session_factory = lambda: _ctx(test_db)
    try:
        request = _make_request(user_auth_token)
        user = await get_current_user_for_stream(request, user_auth_token)
        assert str(user.id) == str(mock_user.id)
    finally:
        deps_mod.stream_auth_session_factory = deps_mod.AsyncSessionLocal


async def test_sse_auth_helper_rejects_invalid_token(test_db):
    deps_mod.stream_auth_session_factory = lambda: _ctx(test_db)
    try:
        request = _make_request("not-a-token")
        with pytest.raises(Exception) as exc:
            await get_current_user_for_stream(request, "not-a-token")
        # FastAPI/Starlette HTTPException has status_code 401
        assert getattr(exc.value, "status_code", None) == 401
    finally:
        deps_mod.stream_auth_session_factory = deps_mod.AsyncSessionLocal


class _TrackingSession:
    """Wraps test_db and records whether __aexit__ ran."""

    def __init__(self, db):
        self.db = db
        self.closed = False

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        self.closed = True
        return False


@contextlib.asynccontextmanager
async def _ctx(db):
    yield db


def _make_request(token):
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/reviews/stream",
        "query_string": b"",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
    }
    return Request(scope)


async def test_sse_auth_session_closed_before_streaming(test_db, mock_user, user_auth_token):
    created: list[_TrackingSession] = []

    def tracking_factory():
        ts = _TrackingSession(test_db)
        created.append(ts)
        return ts

    deps_mod.stream_auth_session_factory = tracking_factory
    try:
        request = _make_request(user_auth_token)
        user = await get_current_user_for_stream(request, user_auth_token)
        assert str(user.id) == str(mock_user.id)
        assert created, "session factory was not invoked"
        assert created[-1].closed, "auth session was not closed before returning"
    finally:
        deps_mod.stream_auth_session_factory = deps_mod.AsyncSessionLocal


async def test_sse_auth_session_closed_on_auth_failure(test_db):
    created: list[_TrackingSession] = []

    def tracking_factory():
        ts = _TrackingSession(test_db)
        created.append(ts)
        return ts

    deps_mod.stream_auth_session_factory = tracking_factory
    try:
        request = _make_request("bad-token")
        with pytest.raises(Exception) as exc:
            await get_current_user_for_stream(request, "bad-token")
        assert getattr(exc.value, "status_code", None) == 401
        assert created and created[-1].closed
    finally:
        deps_mod.stream_auth_session_factory = deps_mod.AsyncSessionLocal