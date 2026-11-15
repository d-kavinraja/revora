"""Regression tests for GitHub installation token 404 handling and auth status."""
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.github.auth import GitHubAppAuth, github_app_auth
from app.github.errors import GitHubConfigurationError, GitHubTransientError


@pytest.fixture
def fresh_auth(monkeypatch):
    """A fresh GitHubAppAuth instance with test credentials."""
    auth = GitHubAppAuth()
    monkeypatch.setattr("app.github.auth.settings.GITHUB_APP_ID", "4265854", raising=False)
    monkeypatch.setattr("app.github.auth.settings.GITHUB_APP_PRIVATE_KEY", "fake-key", raising=False)
    # Patch _create_app_jwt to avoid real JWT signing
    monkeypatch.setattr(auth, "_create_app_jwt", lambda: "fake-jwt")
    return auth


async def test_fresh_token_generation(fresh_auth, monkeypatch):
    """Fresh token is generated and cached when no cached token exists."""
    mock_response = httpx.Response(
        201,
        json={"token": "ghs_fresh_token", "expires_at": "2026-12-01T00:00:00Z"},
        request=httpx.Request("POST", "https://api.github.com/x"),
    )
    async def mock_post(*args, **kwargs):
        return mock_response
    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

    token = await fresh_auth.get_installation_token(12345)
    assert token == "ghs_fresh_token"
    # Verify it's cached
    cached = fresh_auth._token_cache.get(("4265854", 12345))
    assert cached is not None
    assert cached[0] == "ghs_fresh_token"


async def test_cached_token_retrieval(fresh_auth, monkeypatch):
    """Cached token is returned without calling GitHub."""
    future = datetime.now(UTC) + timedelta(hours=1)
    fresh_auth._token_cache[("4265854", 12345)] = ("cached_token", future)

    # Mock httpx to fail if called
    async def mock_post(*args, **kwargs):
        raise RuntimeError("Should not be called")
    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

    token = await fresh_auth.get_installation_token(12345)
    assert token == "cached_token"


async def test_404_invalidates_cache(fresh_auth, monkeypatch):
    """HTTP 404 invalidates the cached token."""
    # Pre-populate cache with a token that is about to expire
    past = datetime.now(UTC) - timedelta(hours=1)
    fresh_auth._token_cache[("4265854", 12345)] = ("stale_token", past)

    mock_response = httpx.Response(
        404,
        request=httpx.Request("POST", "https://api.github.com/x"),
    )
    async def mock_post(*args, **kwargs):
        return mock_response
    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

    with pytest.raises(GitHubConfigurationError) as exc_info:
        await fresh_auth.get_installation_token(12345)

    assert exc_info.value.status_code == 404
    assert exc_info.value.retryable is False
    assert exc_info.value.category == "installation_not_found"
    # Cache should be invalidated
    assert ("4265854", 12345) not in fresh_auth._token_cache


async def test_404_classified_non_retryable(fresh_auth, monkeypatch):
    """HTTP 404 is classified as non-retryable."""
    mock_response = httpx.Response(
        404,
        request=httpx.Request("POST", "https://api.github.com/x"),
    )
    async def mock_post(*args, **kwargs):
        return mock_response
    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

    with pytest.raises(GitHubConfigurationError) as exc_info:
        await fresh_auth.get_installation_token(99999)

    assert exc_info.value.retryable is False


async def test_5xx_remains_transient(fresh_auth, monkeypatch):
    """HTTP 5xx remains transient and retryable."""
    mock_response = httpx.Response(
        500,
        request=httpx.Request("POST", "https://api.github.com/x"),
    )
    async def mock_post(*args, **kwargs):
        return mock_response
    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

    with pytest.raises(GitHubTransientError) as exc_info:
        await fresh_auth.get_installation_token(12345)

    assert exc_info.value.retryable is True
    assert exc_info.value.status_code == 500


async def test_network_timeout_remains_transient(fresh_auth, monkeypatch):
    """Network timeout remains transient and retryable."""
    async def mock_post(*args, **kwargs):
        raise httpx.TimeoutException("timed out")
    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

    with pytest.raises(GitHubTransientError) as exc_info:
        await fresh_auth.get_installation_token(12345)

    assert exc_info.value.retryable is True
    assert exc_info.value.status_code is None


async def test_token_cache_key_scoped_to_app_and_installation(fresh_auth):
    """Cache key includes both app_id and installation_id."""
    assert ("4265854", 12345) not in fresh_auth._token_cache
    # Different app_id → different cache key
    fresh_auth._token_cache[("other-app", 12345)] = ("other_token", datetime.now(UTC) + timedelta(hours=1))
    # Should not return the other app's token
    assert ("4265854", 12345) not in fresh_auth._token_cache


async def test_get_installation_token_with_status_cached(fresh_auth, monkeypatch):
    """get_installation_token_with_status reports was_cached=True for cached tokens."""
    future = datetime.now(UTC) + timedelta(hours=1)
    fresh_auth._token_cache[("4265854", 12345)] = ("cached_token", future)

    async def mock_post(*args, **kwargs):
        raise RuntimeError("Should not be called")
    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

    token, was_cached = await fresh_auth.get_installation_token_with_status(12345)
    assert token == "cached_token"
    assert was_cached is True


async def test_get_installation_token_with_status_fresh(fresh_auth, monkeypatch):
    """get_installation_token_with_status reports was_cached=False for fresh tokens."""
    mock_response = httpx.Response(
        201,
        json={"token": "ghs_fresh", "expires_at": "2026-12-01T00:00:00Z"},
        request=httpx.Request("POST", "https://api.github.com/x"),
    )
    async def mock_post(*args, **kwargs):
        return mock_response
    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

    token, was_cached = await fresh_auth.get_installation_token_with_status(12345)
    assert token == "ghs_fresh"
    assert was_cached is False
