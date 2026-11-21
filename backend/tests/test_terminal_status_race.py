"""Deterministic terminal-status interleaving tests (in-memory, no external calls)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update
from sqlalchemy.sql.dml import Update

from app.models.review import Review
from app.pipeline import orchestrator as pipeline_module
from app.pipeline.orchestrator import review_pipeline
from app.services.review_execution_service import (
    create_execution,
    get_latest_execution,
    mark_execution_final,
)

MODEL = "qwen3.8-27b"


async def _seed_review(test_db, *, status: str = "running"):
    review = Review(
        pr_id=uuid.uuid4(), status=status, started_at=datetime.now(UTC)
    )
    test_db.add(review)
    await test_db.commit()
    await test_db.refresh(review)
    await create_execution(
        test_db,
        review.id,
        trigger="webhook",
        provider="kllm",
        model=MODEL,
    )
    await test_db.commit()
    return review


async def _cancel_now(test_db, review_id):
    await test_db.execute(
        update(Review)
        .where(Review.id == review_id)
        .values(status="cancelled")
    )
    await mark_execution_final(
        test_db, review_id, "cancelled", error_message="Cancelled by user"
    )
    await test_db.commit()


class InterleavingSession:
    """Interposes a concurrent cancellation between stale read and UPDATE."""

    def __init__(self, delegate, on_execute):
        self.delegate = delegate
        self.on_execute = on_execute
        self.interleaved = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def execute(self, stmt, *args, **kwargs):
        if (
            not self.interleaved
            and self.on_execute is not None
            and getattr(getattr(stmt, "table", None), "name", None) == "reviews"
            and isinstance(stmt, Update)
        ):
            self.interleaved = True
            await self.on_execute()
        return await self.delegate.execute(stmt, *args, **kwargs)

    async def scalar(self, *args, **kwargs):
        return await self.delegate.scalar(*args, **kwargs)

    async def commit(self):
        return await self.delegate.commit()

    async def flush(self):
        return await self.delegate.flush()


def _llm_response():
    return SimpleNamespace(
        provider="kllm",
        model=MODEL,
        content="",
        input_tokens=1,
        output_tokens=1,
        latency_ms=1.0,
        estimated_cost_usd=0.0,
        is_fallback=False,
    )


async def _patch_usage_disabled(test_db, monkeypatch):
    monkeypatch.setattr(
        pipeline_module.platform_settings_service,
        "is_usage_analytics_enabled",
        _return_false,
    )


async def _return_false():
    return False


async def _noop():
    return None


async def _assert_cancelled(test_db, review_id):
    review = (
        await test_db.execute(select(Review).where(Review.id == review_id))
    ).scalars().first()
    execution = await get_latest_execution(test_db, review_id)
    assert review.status == "cancelled"
    assert execution.status == "cancelled"
    assert execution.error_message == "Cancelled by user"


async def test_cancellation_before_completion_persistence_is_preserved(
    test_db, monkeypatch
):
    review = await _seed_review(test_db)
    session = InterleavingSession(
        test_db, lambda: _cancel_now(test_db, review.id)
    )
    monkeypatch.setattr(pipeline_module, "AsyncSessionLocal", lambda: session)

    await review_pipeline._save_completed(
        review.id,
        SimpleNamespace(verified_count=0, rejected_count=0),
        _llm_response(),
        {},
        0,
    )

    assert session.interleaved is True
    await _assert_cancelled(test_db, review.id)


async def test_cancellation_before_failure_persistence_is_preserved(
    test_db, monkeypatch
):
    review = await _seed_review(test_db)
    session = InterleavingSession(
        test_db, lambda: _cancel_now(test_db, review.id)
    )
    monkeypatch.setattr(pipeline_module, "AsyncSessionLocal", lambda: session)

    await review_pipeline._save_failed(review.id, "provider failed")

    assert session.interleaved is True
    await _assert_cancelled(test_db, review.id)


async def test_completion_persists_without_cancellation(test_db, monkeypatch):
    review = await _seed_review(test_db)
    await _patch_usage_disabled(test_db, monkeypatch)
    monkeypatch.setattr(
        pipeline_module,
        "AsyncSessionLocal",
        lambda: InterleavingSession(test_db, _noop),
    )

    await review_pipeline._save_completed(
        review.id,
        SimpleNamespace(verified_count=1, rejected_count=0),
        _llm_response(),
        {},
        0,
    )

    review = (
        await test_db.execute(select(Review).where(Review.id == review.id))
    ).scalars().first()
    execution = await get_latest_execution(test_db, review.id)
    assert review.status == "completed"
    assert review.completed_at is not None
    assert execution.status == "completed"


async def test_failure_persists_without_cancellation(test_db, monkeypatch):
    review = await _seed_review(test_db)
    monkeypatch.setattr(
        pipeline_module,
        "AsyncSessionLocal",
        lambda: InterleavingSession(test_db, _noop),
    )

    await review_pipeline._save_failed(review.id, "provider failed")

    review = (
        await test_db.execute(select(Review).where(Review.id == review.id))
    ).scalars().first()
    execution = await get_latest_execution(test_db, review.id)
    assert review.status == "failed"
    assert review.completed_at is not None
    assert execution.status == "failed"
    assert execution.error_message == "provider failed"
