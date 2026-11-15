"""PR review publication: idempotency and transient-error handling.

A 404 on the previous Revora review creates a fresh one; any other error
must surface instead of silently stacking a duplicate review.
"""
from unittest.mock import AsyncMock

import httpx
import pytest

from app.github.client import github_client
from app.pipeline.orchestrator import review_pipeline


def _response(status_code: int) -> httpx.Response:
    request = httpx.Request("PATCH", "https://api.github.com/x")
    return httpx.Response(status_code, request=request)


def _http_error(status_code: int) -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError(
        f"{status_code} error",
        request=httpx.Request("PATCH", "https://api.github.com/x"),
        response=_response(status_code),
    )


@pytest.fixture
def existing_review():
    return {
        "id": 5304086901,
        "body": "Revora AI Review: findings...",
        "submitted_at": "2026-11-15T09:00:00Z",
    }


async def test_update_success_patches_existing_review(
    monkeypatch, existing_review
):
    monkeypatch.setattr(
        github_client, "list_pr_reviews", AsyncMock(return_value=[existing_review])
    )
    update_mock = AsyncMock(return_value={"id": existing_review["id"]})
    monkeypatch.setattr(github_client, "update_pr_review", update_mock)
    create_mock = AsyncMock()
    monkeypatch.setattr(github_client, "create_pr_review", create_mock)

    result = await review_pipeline._publish_or_update_pr_review(
        installation_id=1,
        owner="o",
        repo="r",
        pr_number=26,
        body="new body",
        event="COMMENT",
    )

    assert result == existing_review["id"]
    update_mock.assert_awaited_once()
    create_mock.assert_not_awaited()


async def test_update_404_creates_fresh_review(
    monkeypatch, existing_review
):
    monkeypatch.setattr(
        github_client, "list_pr_reviews", AsyncMock(return_value=[existing_review])
    )
    monkeypatch.setattr(
        github_client, "update_pr_review", AsyncMock(side_effect=_http_error(404))
    )
    create_mock = AsyncMock(return_value={"id": 999})
    monkeypatch.setattr(github_client, "create_pr_review", create_mock)

    result = await review_pipeline._publish_or_update_pr_review(
        installation_id=1,
        owner="o",
        repo="r",
        pr_number=26,
        body="new body",
        event="COMMENT",
    )

    assert result == 999
    create_mock.assert_awaited_once()


async def test_transient_error_does_not_create_duplicate(
    monkeypatch, existing_review
):
    monkeypatch.setattr(
        github_client, "list_pr_reviews", AsyncMock(return_value=[existing_review])
    )
    monkeypatch.setattr(
        github_client, "update_pr_review", AsyncMock(side_effect=_http_error(500))
    )
    create_mock = AsyncMock(return_value={"id": 999})
    monkeypatch.setattr(github_client, "create_pr_review", create_mock)

    with pytest.raises(httpx.HTTPStatusError):
        await review_pipeline._publish_or_update_pr_review(
            installation_id=1,
            owner="o",
            repo="r",
            pr_number=26,
            body="new body",
            event="COMMENT",
        )

    create_mock.assert_not_awaited()


async def test_list_timeout_does_not_create(monkeypatch):
    monkeypatch.setattr(
        github_client,
        "list_pr_reviews",
        AsyncMock(side_effect=TimeoutError("timed out")),
    )
    create_mock = AsyncMock(return_value={"id": 1234})
    monkeypatch.setattr(github_client, "create_pr_review", create_mock)

    with pytest.raises(TimeoutError):
        await review_pipeline._publish_or_update_pr_review(
            installation_id=1,
            owner="o",
            repo="r",
            pr_number=26,
            body="new body",
            event="COMMENT",
        )

    create_mock.assert_not_awaited()


async def test_list_5xx_does_not_create(monkeypatch):
    import httpx

    response = httpx.Response(500, request=httpx.Request("GET", "https://api.github.com/x"))
    error = httpx.HTTPStatusError("server error", request=response.request, response=response)
    monkeypatch.setattr(
        github_client,
        "list_pr_reviews",
        AsyncMock(side_effect=error),
    )
    create_mock = AsyncMock(return_value={"id": 1234})
    monkeypatch.setattr(github_client, "create_pr_review", create_mock)

    with pytest.raises(httpx.HTTPStatusError):
        await review_pipeline._publish_or_update_pr_review(
            installation_id=1,
            owner="o",
            repo="r",
            pr_number=26,
            body="new body",
            event="COMMENT",
        )

    create_mock.assert_not_awaited()


async def test_successful_empty_list_creates_new(monkeypatch):
    monkeypatch.setattr(
        github_client,
        "list_pr_reviews",
        AsyncMock(return_value=[]),
    )
    create_mock = AsyncMock(return_value={"id": 5678})
    monkeypatch.setattr(github_client, "create_pr_review", create_mock)

    result = await review_pipeline._publish_or_update_pr_review(
        installation_id=1,
        owner="o",
        repo="r",
        pr_number=26,
        body="new body",
        event="COMMENT",
    )

    assert result == 5678
    create_mock.assert_awaited_once()


async def test_matching_review_updates_not_creates(monkeypatch):
    existing = {
        "id": 5304086901,
        "body": "Revora AI Review: findings...",
        "submitted_at": "2026-11-15T09:00:00Z",
    }
    monkeypatch.setattr(
        github_client, "list_pr_reviews", AsyncMock(return_value=[existing])
    )
    update_mock = AsyncMock(return_value={"id": existing["id"]})
    monkeypatch.setattr(github_client, "update_pr_review", update_mock)
    create_mock = AsyncMock()
    monkeypatch.setattr(github_client, "create_pr_review", create_mock)

    result = await review_pipeline._publish_or_update_pr_review(
        installation_id=1,
        owner="o",
        repo="r",
        pr_number=26,
        body="new body",
        event="COMMENT",
    )

    assert result == existing["id"]
    update_mock.assert_awaited_once()
    create_mock.assert_not_awaited()


async def test_update_404_creates_replacement(monkeypatch):
    existing = {
        "id": 5304086901,
        "body": "Revora AI Review: findings...",
        "submitted_at": "2026-11-15T09:00:00Z",
    }
    monkeypatch.setattr(
        github_client, "list_pr_reviews", AsyncMock(return_value=[existing])
    )

    import httpx

    response = httpx.Response(404, request=httpx.Request("PATCH", "https://api.github.com/x"))
    error = httpx.HTTPStatusError("not found", request=response.request, response=response)
    monkeypatch.setattr(
        github_client, "update_pr_review", AsyncMock(side_effect=error)
    )
    create_mock = AsyncMock(return_value={"id": 9999})
    monkeypatch.setattr(github_client, "create_pr_review", create_mock)

    result = await review_pipeline._publish_or_update_pr_review(
        installation_id=1,
        owner="o",
        repo="r",
        pr_number=26,
        body="new body",
        event="COMMENT",
    )

    assert result == 9999
    create_mock.assert_awaited_once()


async def test_transient_update_error_raises_no_duplicate(monkeypatch):
    existing = {
        "id": 5304086901,
        "body": "Revora AI Review: findings...",
        "submitted_at": "2026-11-15T09:00:00Z",
    }
    monkeypatch.setattr(
        github_client, "list_pr_reviews", AsyncMock(return_value=[existing])
    )

    import httpx

    response = httpx.Response(500, request=httpx.Request("PATCH", "https://api.github.com/x"))
    error = httpx.HTTPStatusError("server error", request=response.request, response=response)
    monkeypatch.setattr(
        github_client, "update_pr_review", AsyncMock(side_effect=error)
    )
    create_mock = AsyncMock(return_value={"id": 9999})
    monkeypatch.setattr(github_client, "create_pr_review", create_mock)

    with pytest.raises(httpx.HTTPStatusError):
        await review_pipeline._publish_or_update_pr_review(
            installation_id=1,
            owner="o",
            repo="r",
            pr_number=26,
            body="new body",
            event="COMMENT",
        )

    create_mock.assert_not_awaited()


async def test_no_previous_review_creates_new(monkeypatch):
    monkeypatch.setattr(
        github_client,
        "list_pr_reviews",
        AsyncMock(return_value=[{"id": 1, "body": "someone else's review", "submitted_at": "2026-11-15T09:00:00Z"}]),
    )
    create_mock = AsyncMock(return_value={"id": 77})
    monkeypatch.setattr(github_client, "create_pr_review", create_mock)

    result = await review_pipeline._publish_or_update_pr_review(
        installation_id=1,
        owner="o",
        repo="r",
        pr_number=26,
        body="new body",
        event="COMMENT",
    )

    assert result == 77
