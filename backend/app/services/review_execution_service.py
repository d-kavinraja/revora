"""ReviewExecutionService — helpers for tracking review execution history.

Each run of a review lifecycle (webhook trigger, rerun, retry, restart)
creates one ReviewExecution row. The reviews table keeps a single row per
pull request lifecycle; executions record the per-run history.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import ReviewExecution

logger = logging.getLogger(__name__)


async def create_execution(
    db: AsyncSession,
    review_id,
    trigger: str,
    commit_sha: str | None = None,
) -> ReviewExecution:
    """Create a new execution for a review with the next execution number."""
    next_number = await db.scalar(
        select(func.coalesce(func.max(ReviewExecution.execution_number), 0))
        .where(ReviewExecution.review_id == review_id)
    )
    execution = ReviewExecution(
        review_id=review_id,
        execution_number=(next_number or 0) + 1,
        trigger=trigger,
        status="queued",
        commit_sha=commit_sha,
    )
    db.add(execution)
    await db.flush()
    logger.info(f"Created execution #{execution.execution_number} ({trigger}) for review {review_id}")
    return execution


async def get_latest_execution(
    db: AsyncSession,
    review_id,
) -> ReviewExecution | None:
    result = await db.execute(
        select(ReviewExecution)
        .where(ReviewExecution.review_id == review_id)
        .order_by(ReviewExecution.execution_number.desc())
        .limit(1)
    )
    return result.scalars().first()


async def mark_execution_running(db: AsyncSession, review_id) -> ReviewExecution | None:
    """Flip the latest execution of a review to 'running'."""
    execution = await get_latest_execution(db, review_id)
    if execution and execution.status == "queued":
        execution.status = "running"
        execution.started_at = datetime.now(UTC)
        db.add(execution)
        await db.flush()
    return execution


async def mark_execution_final(
    db: AsyncSession,
    review_id,
    status: str,
    duration_ms: int | None = None,
    model: str | None = None,
    provider: str | None = None,
    tokens: dict[str, Any] | None = None,
) -> None:
    """Mark the latest execution of a review as completed/failed/cancelled."""
    execution = await get_latest_execution(db, review_id)
    if not execution:
        return
    now = datetime.now(UTC)
    execution.status = status
    execution.completed_at = now
    if duration_ms is not None:
        execution.duration_ms = duration_ms
    if model:
        execution.model = model
    if provider:
        execution.provider = provider
    if tokens:
        execution.tokens = tokens
    if execution.started_at is None:
        execution.started_at = now
    db.add(execution)
    await db.flush()
    logger.info(f"Marked execution #{execution.execution_number} for review {review_id} as {status}")


async def cancel_active_executions(db: AsyncSession, review_id) -> int:
    """Mark all non-terminal executions of a review as cancelled (supersede)."""
    result = await db.execute(
        update(ReviewExecution)
        .where(
            ReviewExecution.review_id == review_id,
            ReviewExecution.status.in_(["queued", "running", "pending"]),
        )
        .values(status="cancelled")
    )
    return result.rowcount or 0
