"""Dispatcher for enqueuing review jobs with idempotency and lifecycle rules.

Review lifecycle rules (one review row per PR lifecycle):
  - opened  → create a NEW Review row (first lifecycle)
  - reopened → create a NEW Review row (old row stays as history)
  - synchronize → REUSE the latest Review row, supersede any in-flight run
"""

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
    webhook_action: str = "opened",
) -> Optional[ReviewJob]:
    """Enqueue a review job with idempotency and lifecycle-aware review handling.

    Uses INSERT ... ON CONFLICT DO NOTHING to deduplicate on
    (delivery_id, head_sha).

    Args:
        session: Async database session.
        payload: GitHub webhook payload.
        delivery_id: X-GitHub-Delivery GUID.
        webhook_action: pull_request action — "opened", "reopened", or
            "synchronize". Determines whether a new Review row is created
            (opened/reopened) or the latest row is reused (synchronize).

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

    db_pr = None
    if repo_id:
        from app.models.github import PullRequest as PRModel
        from app.models.review import Review as ReviewModel
        pr_find = await session.execute(
            select(PRModel).where(
                PRModel.repo_id == repo_id,
                PRModel.pr_number == pr_number,
            )
        )
        db_pr = pr_find.scalars().first()
        if db_pr:
            active = await session.execute(
                select(ReviewModel).where(
                    ReviewModel.pr_id == db_pr.id,
                    ReviewModel.status.in_(["queued", "pending", "running"]),
                )
            )
            if active.scalars().first():
                if webhook_action == "synchronize":
                    # Supersede the in-flight run: cancel its jobs and
                    # executions, then reuse the same Review row below.
                    await _supersede_inflight(session, db_pr, payload, head_sha)
                    logger.info(f"Superseding in-flight review for PR #{pr_number} on new commit")
                else:
                    logger.info(f"Active review exists for PR #{pr_number} — skipping webhook enqueue")
                    return None

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
        logger.info(f"Enqueued review job {job.id} for PR #{pr_number} (action={webhook_action})")

        # Create/reuse the Review record immediately so UI shows "Pending"
        try:
            from app.github.shared import get_or_create_review_records
            installation_id = installation.get("id")
            if installation_id:
                if webhook_action == "synchronize" and db_pr is not None:
                    await _reuse_latest_review_for_pr(
                        session, db_pr, payload, installation_id, head_sha
                    )
                else:
                    await get_or_create_review_records(
                        installation_id=installation_id,
                        repository=repository,
                        pull_request=pull_request,
                        delivery_id=delivery_id,
                        status="pending",
                        find_existing_pending=False,  # opened/reopened: always a new row
                    )
        except Exception as e:
            logger.error(f"Failed to create pending Review record: {e}", exc_info=True)

        return job
    else:
        logger.info(f"Duplicate job ignored: delivery={delivery_id} sha={head_sha[:12]}")
        return None


async def _supersede_inflight(session, db_pr, payload: Dict[str, Any], new_sha: str) -> None:
    """Cancel in-flight jobs and executions for a PR before a new commit run.

    The Review row itself is untouched here — it is reset by
    _reuse_latest_review_for_pr.
    """
    from app.models.review import Review
    from app.services.review_execution_service import cancel_active_executions

    await supersede_jobs(session, payload.get("repository", {}), db_pr.pr_number, new_sha)

    active_reviews = await session.execute(
        select(Review).where(
            Review.pr_id == db_pr.id,
            Review.status.in_(["queued", "pending", "running"]),
        )
    )
    for rev in active_reviews.scalars().all():
        await cancel_active_executions(session, rev.id)


async def _reuse_latest_review_for_pr(session, db_pr, payload: Dict[str, Any], installation_id: int, head_sha: str) -> None:
    """Reuse the latest Review row for a PR (synchronize event).

    Resets the row to 'pending', clears stale content, and creates a new
    ReviewExecution. If the PR has no Review row yet (first push), creates one.
    """
    from app.models.review import Review
    from app.services.review_execution_service import create_execution

    latest = await session.execute(
        select(Review).where(Review.pr_id == db_pr.id).order_by(Review.created_at.desc()).limit(1)
    )
    db_review = latest.scalars().first()

    if not db_review:
        db_review = Review(pr_id=db_pr.id, status="pending")
        session.add(db_review)
        await session.flush()
        logger.info(f"Created Review record {db_review.id} for reused PR #{db_pr.pr_number}")

    db_review.status = "pending"
    db_review.started_at = None
    db_review.completed_at = None
    db_review.error_message = None
    db_review.summary = None
    session.add(db_review)
    await session.flush()

    await create_execution(session, db_review.id, trigger="webhook", commit_sha=head_sha)
    await session.commit()
    logger.info(f"Reused Review {db_review.id} for synchronize on PR #{db_pr.pr_number}")


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


async def enqueue_lifecycle_job(
    session,
    payload: Dict[str, Any],
    delivery_id: str,
    repo_id: Optional[UUID] = None,
    pr_number: Optional[int] = None,
    head_sha: Optional[str] = None,
) -> Optional[ReviewJob]:
    """Enqueue a lifecycle job (rerun, retry, restart).

    Unlike regular webhook jobs, lifecycle jobs may have explicit repo_id/pr_number/sha.

    Args:
        session: Async database session.
        payload: GitHub webhook payload with _lifecycle metadata.
        delivery_id: Unique delivery identifier.
        repo_id: Explicit repository ID.
        pr_number: Explicit PR number.
        head_sha: Explicit HEAD SHA.

    Returns:
        The created ReviewJob, or None if duplicate.
    """
    pull_request = payload.get("pull_request", {})
    installation = payload.get("installation", {})

    target_head_sha = head_sha or pull_request.get("head", {}).get("sha", "")
    target_pr_number = pr_number or pull_request.get("number", 0)
    target_repo_id = repo_id

    stmt = (
        pg_insert(ReviewJob)
        .values(
            delivery_id=delivery_id,
            head_sha=target_head_sha,
            pr_number=target_pr_number,
            repo_id=target_repo_id,
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
        lifecycle_action = payload.get("_lifecycle", {}).get("action", "unknown")
        logger.info(f"Enqueued lifecycle job ({lifecycle_action}) {job.id} for PR #{target_pr_number}")
        return job

    return None
