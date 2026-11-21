"""Cancellation and GitHub comment idempotency tests (all external calls mocked)."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from app.models.review import Review
from app.pipeline import orchestrator as pipeline_module
from app.pipeline.orchestrator import ReviewPipeline, review_pipeline


class _FakeEmitter:
    async def emit(self, *_args, **_kwargs):
        return None

    async def emit_log(self, *_args, **_kwargs):
        return None

    async def emit_error(self, *_args, **_kwargs):
        return None


class _Summary:
    body = "summary"
    event = "COMMENT"
    comments = []


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request(
        "PATCH",
        "https://api.github.com/repos/owner/repo/issues/comments/123",
    )
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(f"HTTP {status}", request=request, response=response)


async def test_stage_publish_raises_cancelled_before_any_publish():
    monkeypatch = pytest.MonkeyPatch()
    try:
        # Other suites have historically replaced this singleton method
        # directly; restore the real implementation for this assertion.
        real_publish = ReviewPipeline._stage_publish.__get__(
            review_pipeline, ReviewPipeline
        )
        monkeypatch.setattr(review_pipeline, "_stage_publish", real_publish)
        monkeypatch.setattr(
            pipeline_module.github_review_generator,
            "generate",
            AsyncMock(return_value=_Summary()),
        )
        with pytest.raises(asyncio.CancelledError):
            await review_pipeline._stage_publish(
                _FakeEmitter(),
                object(),
                "title",
                1,
                "owner",
                "repo",
                1,
                {},
                object(),
                0,
                cancel_check=lambda: _cancelled_true(),
            )
    finally:
        monkeypatch.undo()


async def _cancelled_true() -> bool:
    return True


class _HermeticResult:
    def scalars(self):
        return self

    def first(self):
        return None


class _HermeticSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def execute(self, *_args, **_kwargs):
        return _HermeticResult()

    async def commit(self):
        return None

    async def flush(self):
        return None


async def test_pipeline_does_not_save_completed_when_publish_is_cancelled(
    monkeypatch,
):
    monkeypatch.setattr(
        pipeline_module, "AsyncSessionLocal", lambda: _HermeticSession()
    )
    monkeypatch.setattr(pipeline_module, "SSEEmitter", lambda *_args: _FakeEmitter())
    monkeypatch.setattr(
        "app.services.timeline_recorder.record_stage", AsyncMock()
    )
    monkeypatch.setattr(review_pipeline, "_stage_clone", AsyncMock(return_value=None))
    monkeypatch.setattr(review_pipeline, "_stage_intelligence", AsyncMock(return_value={}))
    monkeypatch.setattr(review_pipeline, "_stage_indexing", AsyncMock(return_value=None))
    monkeypatch.setattr(
        review_pipeline, "_stage_knowledge", AsyncMock(return_value=("", [], None))
    )
    monkeypatch.setattr(review_pipeline, "_stage_retrieval", AsyncMock(return_value=None))
    monkeypatch.setattr(review_pipeline, "_stage_prompt", AsyncMock(return_value=object()))
    monkeypatch.setattr(
        review_pipeline,
        "_stage_llm",
        AsyncMock(
            return_value=SimpleNamespace(
                provider="kllm",
                model="qwen3.8-27b",
                content="",
                input_tokens=1,
                output_tokens=1,
                estimated_cost_usd=0.0,
                is_fallback=False,
            )
        ),
    )
    monkeypatch.setattr(
        review_pipeline,
        "_stage_verification",
        AsyncMock(return_value=type("V", (), {"verified_count": 0, "rejected_count": 0})()),
    )
    publish = AsyncMock(side_effect=asyncio.CancelledError())
    save_completed = AsyncMock()
    monkeypatch.setattr(review_pipeline, "_stage_publish", publish)
    monkeypatch.setattr(review_pipeline, "_save_completed", save_completed)

    with pytest.raises(asyncio.CancelledError):
        await review_pipeline.execute(
            review_id=uuid.uuid4(),
            installation_id=1,
            owner="owner",
            repo_name="repo",
            pr_number=1,
            pr_title="title",
            pr_description="",
            head_sha="abc",
            diff_content="",
            user_id="00000000-0000-0000-0000-000000000000",
            provider="kllm",
            model="qwen3.8-27b",
        )
    publish.assert_awaited_once()
    save_completed.assert_not_awaited()


async def test_save_completed_does_not_overwrite_confirmed_cancellation(
    test_db, monkeypatch
):
    review = Review(pr_id=uuid.uuid4(), status="cancelled")
    test_db.add(review)
    await test_db.commit()
    await test_db.refresh(review)

    class SessionWrapper:
        async def __aenter__(self):
            return test_db

        async def __aexit__(self, *_exc):
            return False

    monkeypatch.setattr(pipeline_module, "AsyncSessionLocal", lambda: SessionWrapper())
    await review_pipeline._save_completed(review.id, object(), object(), {}, None)

    refreshed = (
        await test_db.execute(select(Review).where(Review.id == review.id))
    ).scalars().first()
    assert refreshed.status == "cancelled"


async def _seed_review_with_comment(test_db):
    review = Review(
        pr_id=uuid.uuid4(), status="completed", github_comment_id=424242
    )
    test_db.add(review)
    await test_db.commit()
    await test_db.refresh(review)
    return review


def _session_wrapper(test_db):
    class SessionWrapper:
        async def __aenter__(self):
            return test_db

        async def __aexit__(self, *_exc):
            return False

    return SessionWrapper


async def test_summary_comment_update_success_does_not_create_duplicate(
    test_db, monkeypatch
):
    review = await _seed_review_with_comment(test_db)
    monkeypatch.setattr(
        pipeline_module, "AsyncSessionLocal", lambda: _session_wrapper(test_db)()
    )
    update = AsyncMock(return_value={"id": 424242})
    create = AsyncMock()
    monkeypatch.setattr(
        pipeline_module.github_client, "update_issue_comment", update
    )
    monkeypatch.setattr(
        pipeline_module.github_client, "create_issue_comment", create
    )

    await review_pipeline._upsert_summary_comment(
        1, "owner", "repo", 1, "body", review_id=review.id
    )
    update.assert_awaited_once()
    create.assert_not_awaited()


async def test_summary_comment_404_creates_replacement(test_db, monkeypatch):
    review = await _seed_review_with_comment(test_db)
    monkeypatch.setattr(
        pipeline_module, "AsyncSessionLocal", lambda: _session_wrapper(test_db)()
    )
    update = AsyncMock(side_effect=_http_error(404))
    create = AsyncMock(return_value={"id": 999})
    monkeypatch.setattr(
        pipeline_module.github_client, "update_issue_comment", update
    )
    monkeypatch.setattr(
        pipeline_module.github_client, "create_issue_comment", create
    )

    result = await review_pipeline._upsert_summary_comment(
        1, "owner", "repo", 1, "body", review_id=review.id
    )
    assert result == 999
    create.assert_awaited_once()


@pytest.mark.parametrize("status", [500, 403, 429])
async def test_summary_comment_non_404_errors_do_not_create_duplicate(
    test_db, monkeypatch, status
):
    review = await _seed_review_with_comment(test_db)
    monkeypatch.setattr(
        pipeline_module, "AsyncSessionLocal", lambda: _session_wrapper(test_db)()
    )
    update = AsyncMock(side_effect=_http_error(status))
    create = AsyncMock()
    monkeypatch.setattr(
        pipeline_module.github_client, "update_issue_comment", update
    )
    monkeypatch.setattr(
        pipeline_module.github_client, "create_issue_comment", create
    )

    result = await review_pipeline._upsert_summary_comment(
        1, "owner", "repo", 1, "body", review_id=review.id
    )
    assert result is None
    create.assert_not_awaited()


async def test_summary_comment_timeout_does_not_create_duplicate(
    test_db, monkeypatch
):
    review = await _seed_review_with_comment(test_db)
    monkeypatch.setattr(
        pipeline_module, "AsyncSessionLocal", lambda: _session_wrapper(test_db)()
    )
    update = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
    create = AsyncMock()
    monkeypatch.setattr(
        pipeline_module.github_client, "update_issue_comment", update
    )
    monkeypatch.setattr(
        pipeline_module.github_client, "create_issue_comment", create
    )

    result = await review_pipeline._upsert_summary_comment(
        1, "owner", "repo", 1, "body", review_id=review.id
    )
    assert result is None
    create.assert_not_awaited()
