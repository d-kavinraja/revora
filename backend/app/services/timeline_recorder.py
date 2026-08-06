"""TimelineRecorder — persists review pipeline stage events to the database."""

import logging
from datetime import UTC
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


async def record_stage(
    db,
    review_id: UUID,
    stage: str,
    status: str,
    message: str = "",
    metrics: dict[str, Any] | None = None,
    duration_ms: float | None = None,
):
    """Record a single pipeline stage event in the review_timelines table."""
    from datetime import datetime

    from app.models.timeline import ReviewTimeline

    timeline = ReviewTimeline(
        review_id=review_id,
        stage=stage,
        status=status,
        started_at=datetime.now(UTC) if status == "running" else None,
        completed_at=(
            datetime.now(UTC) if status in ("completed", "failed", "skipped") else None
        ),
        duration_ms=duration_ms,
        message=message,
        metrics=metrics or {},
    )
    db.add(timeline)
    await db.flush()


async def update_stage_duration(db, review_id: UUID, stage: str, duration_ms: float):
    """Update the duration of an existing timeline entry."""
    from sqlalchemy import select

    from app.models.timeline import ReviewTimeline

    result = await db.execute(
        select(ReviewTimeline).where(
            ReviewTimeline.review_id == review_id,
            ReviewTimeline.stage == stage,
        )
    )
    entry = result.scalars().first()
    if entry:
        entry.duration_ms = duration_ms
        entry.completed_at = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        )
        await db.flush()
