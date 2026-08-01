"""Startup recovery — fail reviews stuck in active statuses after a restart.

recover_stale_reviews_on_startup: fail reviews stuck in active statuses with
no backing queued/running job, so the per-PR active-review lock is always
released after a restart — even when no worker is alive to run its own
crash recovery.

The background PR-state / repository reconciliation loop has moved to
app.services.sync_engine (sync_loop), which also covers new repositories,
new PRs, new commits, missed-review enqueueing, and permission changes.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.github import PullRequest, Repository
from app.models.review import Review
from app.queue.models import ReviewJob, JobStatus
from app.models.sync_run import SYNC_REASON_RECOVERY, SYNC_STATUS_SUCCESS

logger = logging.getLogger(__name__)


async def recover_stale_reviews_on_startup() -> int:
    """Fail reviews stuck in active statuses with no backing job.

    Returns the number of reviews marked failed.
    """
    from app.services.review_execution_service import mark_execution_final

    now = datetime.now(timezone.utc)
    failed_count = 0
    async with AsyncSessionLocal() as db:
        active = (
            await db.execute(
                select(Review).where(Review.status.in_(["queued", "pending", "running"]))
            )
        ).scalars().all()

        for review in active:
            pr = (
                await db.execute(select(PullRequest).where(PullRequest.id == review.pr_id))
            ).scalars().first()
            if not pr:
                continue

            job = (
                await db.execute(
                    select(ReviewJob.id)
                    .where(
                        ReviewJob.repo_id == pr.repo_id,
                        ReviewJob.pr_number == pr.pr_number,
                        ReviewJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
                    )
                    .limit(1)
                )
            ).scalars().first()
            if job is not None:
                continue

            review.status = "failed"
            review.error_message = "Server restarted mid-review — re-run the review."
            review.completed_at = now
            db.add(review)
            await mark_execution_final(db, review.id, "failed")
            failed_count += 1

        # Record this recovery pass in sync_runs (best-effort, audit trail).
        if failed_count:
            try:
                from app.services.sync_engine import record_sync_run

                await record_sync_run(
                    db,
                    reason=SYNC_REASON_RECOVERY,
                    status=SYNC_STATUS_SUCCESS,
                    counts={"repos_failed": failed_count},
                    details={"reviews_failed": failed_count},
                )
            except Exception as e:
                logger.warning(f"Failed to record recovery sync run: {e}")
            await db.commit()
            logger.warning(
                f"Startup recovery: failed {failed_count} stale review(s) "
                f"without a backing job (lock released)"
            )
    return failed_count
