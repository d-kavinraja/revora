"""Dispatcher for enqueuing review jobs with idempotency and supersede logic."""

import logging
from typing import Dict, Any, Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import AsyncSessionLocal
from app.queue.models import ReviewJob, JobStatus

logger = logging.getLogger(__name__)


async def enqueue_review_job(
    session,
    payload: Dict[str, Any],
    delivery_id: str,
) -> Optional[ReviewJob]:
    """Enqueue a review job with idempotency.

    Uses INSERT ... ON CONFLICT DO NOTHING to deduplicate on
    (delivery_id, head_sha).

    Args:
        session: Async database session.
        payload: GitHub webhook payload.
        delivery_id: X-GitHub-Delivery GUID.

    Returns:
        The created ReviewJob, or None if duplicate.
    """
    repository = payload.get("repository", {})
    pull_request = payload.get("pull_request", {})
    installation = payload.get("installation", {})

    head_sha = pull_request.get("head", {}).get("sha", "")
    pr_number = pull_request.get("number", 0)
    repo_github_id = repository.get("id")

    # Resolve repo_id from github_id
    repo_id = None
    if repo_github_id:
        from app.models.github import Repository
        from sqlalchemy import select as sel
        repo_result = await session.execute(
            sel(Repository.id).where(Repository.github_id == repo_github_id)
        )
        repo_id = repo_result.scalar_one_or_none()

    # Supersede any existing jobs for the same PR with a different SHA
    if head_sha:
        await supersede_jobs(session, repository, pr_number, head_sha)

    # Insert with idempotency
    stmt = (
        pg_insert(ReviewJob)
        .values(
            delivery_id=delivery_id,
            head_sha=head_sha,
            pr_number=pr_number,
            repo_id=repo_id,
            payload=payload,
            status=JobStatus.QUEUED,
        )
        .on_conflict_do_nothing(
            index_elements=["delivery_id", "head_sha"],
        )
        .returning(ReviewJob)
    )

    result = await session.execute(stmt)
    job = result.scalar_one_or_none()

    if job:
        await session.commit()
        logger.info(f"Enqueued review job {job.id} for PR #{pr_number}")
        return job
    else:
        logger.info(f"Duplicate job ignored: delivery={delivery_id} sha={head_sha[:12]}")
        return None


async def supersede_jobs(
    session,
    repository: Dict[str, Any],
    pr_number: int,
    new_sha: str,
) -> int:
    """Cancel in-flight jobs for the same PR with a different SHA.

    Called when a new push (synchronize event) arrives for a PR that
    already has a queued or running job.

    Args:
        session: Async database session.
        repository: Repository dict from webhook payload.
        pr_number: Pull request number.
        new_sha: The new HEAD SHA.

    Returns:
        Number of jobs superseded.
    """
    repo_github_id = repository.get("id")

    # Find the repo_id from github_id
    from app.models.github import Repository
    from sqlalchemy import select as sel

    repo_result = await session.execute(
        sel(Repository).where(Repository.github_id == repo_github_id)
    )
    db_repo = repo_result.scalar_one_or_none()

    if not db_repo:
        return 0

    # Cancel jobs for this PR that are queued/running with a different SHA
    stmt = (
        update(ReviewJob)
        .where(
            ReviewJob.repo_id == db_repo.id,
            ReviewJob.pr_number == pr_number,
            ReviewJob.head_sha != new_sha,
            ReviewJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
        )
        .values(status=JobStatus.CANCELLED)
    )
    result = await session.execute(stmt)
    count = result.rowcount

    if count > 0:
        await session.commit()
        logger.info(f"Superseded {count} job(s) for PR #{pr_number} (new SHA: {new_sha[:12]})")

    return count


async def get_pending_jobs(session, limit: int = 1) -> list[ReviewJob]:
    """Get pending jobs using SELECT FOR UPDATE SKIP LOCKED.

    Args:
        session: Async database session.
        limit: Maximum number of jobs to fetch.

    Returns:
        List of queued ReviewJob records.
    """
    from sqlalchemy import text

    stmt = text("""
        SELECT id, repo_id, pr_number, head_sha, delivery_id, payload,
               attempt_count, created_at
        FROM review_jobs
        WHERE status = 'queued'
        ORDER BY created_at ASC
        LIMIT :limit
        FOR UPDATE SKIP LOCKED
    """)

    result = await session.execute(stmt, {"limit": limit})
    rows = result.fetchall()
    return rows
