"""Regression tests for GitHub service PR metadata 404 handling."""
from unittest.mock import AsyncMock

import httpx
import pytest

from app.github.errors import GitHubConfigurationError
from app.services import github_service as gs_module
from app.services.github_service import GitHubService


@pytest.fixture
def service():
    return GitHubService()


async def test_pr_metadata_404_returns_installation_not_found(service, monkeypatch):
    """When installation token returns 404, get_pull_request returns installation_not_found."""
    auth_mock = AsyncMock(side_effect=GitHubConfigurationError(
        "installation_not_found", status_code=404, retryable=False,
        message="GitHub installation not found (deleted or inaccessible).",
    ))
    monkeypatch.setattr("app.services.github_service.github_app_auth.get_installation_token", auth_mock)

    result = await service.get_pull_request("owner/repo", 1, 12345)
    assert result["state"] == "unknown"
    assert result["error"] == "installation_not_found"


async def test_pr_metadata_transient_error_returns_sanitized(service, monkeypatch):
    """Transient errors return sanitized error, not installation_not_found."""
    auth_mock = AsyncMock(side_effect=RuntimeError("network down"))
    monkeypatch.setattr("app.services.github_service.github_app_auth.get_installation_token", auth_mock)

    result = await service.get_pull_request("owner/repo", 1, 12345)
    assert result["state"] == "unknown"
    assert result["error"] != "installation_not_found"


async def test_pr_metadata_http_404_returns_sanitized(service, monkeypatch):
    """HTTP 404 from PR endpoint returns sanitized error."""
    token_mock = AsyncMock(return_value="fake-token")
    monkeypatch.setattr("app.services.github_service.github_app_auth.get_installation_token", token_mock)

    response = httpx.Response(404, request=httpx.Request("GET", "https://api.github.com/x"))
    error = httpx.HTTPStatusError("not found", request=response.request, response=response)

    async def mock_get(*args, **kwargs):
        raise error
    monkeypatch.setattr("httpx.AsyncClient.get", mock_get)

    result = await service.get_pull_request("owner/repo", 1, 12345)
    assert result["state"] == "unknown"
    assert result["error"] != "installation_not_found"
