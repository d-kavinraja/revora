"""One-off cleanup: mark stale/zombie queued reviews as cancelled.

Zombie reviews are rows stuck in "queued"/"pending" whose jobs never
completed (worker crash, cancellation, or pre-fix duplicate-review bug).
They kept the active-review lock held forever.

Run from the backend directory:
    venv\\Scripts\\python scripts\\cleanup_zombie_reviews.py
"""

import asyncio
import logging
import os
import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, update

from app.db.session import AsyncSessionLocal
from app.models.review import Review

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ZOMBIE_AGE_MINUTES = 15
TERMINAL = {"completed", "failed", "cancelled", "stopped", "timed_out"}


async def cleanup():
    cutoff = datetime.now(UTC) - timedelta(minutes=ZOMBIE_AGE_MINUTES)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Review).where(
                Review.status.in_(["queued", "pending"]),
                Review.created_at < cutoff,
            )
        )
        zombies = result.scalars().all()
        if not zombies:
            logger.info("No zombie reviews found.")
            return

        from app.services.review_execution_service import mark_execution_final

        for review in zombies:
            # Do not touch reviews that still have a live job
            from app.queue.models import JobStatus, ReviewJob

            try:
                job_result = await db.execute(
                    select(ReviewJob.id).where(
                        ReviewJob.delivery_id.like(f"%-{review.id}"),
                        ReviewJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
                    )
                )
                if job_result.scalars().first():
                    logger.info(f"Skipping {review.id} — job still queued/running")
                    continue

                # NOTE: reviews has no error_message column — detail goes on
                # the latest execution row.
                await db.execute(
                    update(Review)
                    .where(Review.id == review.id)
                    .values(
                        status="cancelled",
                        completed_at=datetime.now(UTC),
                    )
                )
                await mark_execution_final(
                    db,
                    review.id,
                    "cancelled",
                    error_message="Stale queued review (job never completed) — marked cancelled by cleanup",
                )
                await db.commit()
                logger.info(f"Marked zombie review {review.id} as cancelled")
            except Exception as e:
                await db.rollback()
                logger.error(
                    f"Failed to clean up zombie review {review.id}: {e}",
                    exc_info=True,
                )

        logger.info(f"Cleanup done: {len(zombies)} candidate(s) processed.")


if __name__ == "__main__":
    asyncio.run(cleanup())
