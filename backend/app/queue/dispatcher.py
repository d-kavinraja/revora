"""Dispatcher for enqueuing review jobs with idempotency and lifecycle rules.

Review lifecycle rules (ONE Review row per logical pull request):
  - opened      → create a NEW Review row (first lifecycle). If a Review
                   already exists for the PR (duplicate redelivery), reuse it.
  - reopened    → REUSE the existing Review row (reset to pending + new
                   ReviewExecution with trigger="reopened"). A new Review row
                   is created ONLY as fallback when the original opened event
                   was missed and no Review exists yet.
  - synchronize → REUSE the latest Review row, supersede any in-flight run.

Webhook delivery identity (delivery_id + head_sha) is only used for
duplicate-delivery protection — it is NEVER the logical Review identity,
which is (repository + PR number).
"""

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.queue.models import JobStatus, ReviewJob

logger = logging.getLogger(__name__)


async def enqueue_review_job(
    session,
    payload: dict[str, Any],
    delivery_id: str,
    webhook_action: str = "opened",
    commit: bool = True,
) -> ReviewJob | None:
    """Enqueue a review job with idempotency and lifecycle-aware review handling.

    Uses INSERT ... ON CONFLICT DO NOTHING to deduplicate on
    (delivery_id, head_sha).

    Args:
        session: Async database session.
        payload: GitHub webhook payload.
        delivery_id: X-GitHub-Delivery GUID.
        webhook_action: pull_request action — "opened", "reopened", or
            "synchronize". "opened" creates a Review row only for a genuinely
            new PR; "reopened"/"synchronize" reuse the existing Review row
            for the PR (reset + new ReviewExecution).
        commit: When True (default, webhooks/lifecycle), commit the job and
            Review rows before returning. When False (repository sync),
            flush only and leave the commit to the caller so a whole
            repository's discovery batch becomes visible atomically — the
            worker cannot claim the first job before the remaining PRs are
            created.

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
        from sqlalchemy import select as sel

        from app.models.github import Repository

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
            # Job-level guard: a queued/running job already covers this exact
            # commit — a redelivered webhook (new delivery_id, same sha) must
            # not enqueue a second job for it.
            existing_job = await session.execute(
                select(ReviewJob.id)
                .where(
                    ReviewJob.repo_id == repo_id,
                    ReviewJob.pr_number == pr_number,
                    ReviewJob.head_sha == head_sha,
                    ReviewJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
                )
                .limit(1)
            )
            if existing_job.scalars().first() is not None:
                logger.info(
                    f"Job already queued/running for PR #{pr_number} "
                    f"sha={head_sha[:12]} — skipping webhook enqueue"
                )
                return None

            active = await session.execute(
                select(ReviewModel).where(
                    ReviewModel.pr_id == db_pr.id,
                    ReviewModel.status.in_(["queued", "pending", "running"]),
                )
            )
            if active.scalars().first():
                if webhook_action in ("synchronize", "reopened"):
                    # Supersede the in-flight run: cancel its jobs and
                    # executions, then reuse the same Review row below so the
                    # PR keeps exactly ONE Review card.
                    await _supersede_inflight(session, db_pr, payload, head_sha)
                    logger.info(
                        f"Superseding in-flight review for PR #{pr_number} "
                        f"(action={webhook_action})"
                    )
                else:
                    logger.info(
                        f"Active review exists for PR #{pr_number} — skipping webhook enqueue"
                    )
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
        # Flush (not commit) first so the caller's transaction sees the row.
        # The commit below — or the caller's batch commit when commit=False —
        # is what makes the job visible to the worker. Never let a queued job
        # become visible before its Pending Review row is part of the same
        # commit: create the Review first, then commit both together.
        await session.flush()
        logger.info(
            f"Enqueued review job {job.id} for PR #{pr_number} (action={webhook_action})"
        )

        # Create/reuse the Review record immediately so UI shows "Pending".
        # ONE Review row per logical PR: reopened/synchronize always reuse the
        # existing row; opened creates one only when none exists yet.
        try:
            from app.github.shared import get_or_create_review_records

            installation_id = installation.get("id")
            if installation_id:
                if db_pr is not None:
                    await _reuse_latest_review_for_pr(
                        session,
                        db_pr,
                        payload,
                        installation_id,
                        head_sha,
                        trigger=webhook_action,
                        commit=False,
                    )
                else:
                    # Genuinely new PR (no PullRequest row yet) — full record
                    # creation (installation/repository/PR/Review + execution).
                    await get_or_create_review_records(
                        installation_id=installation_id,
                        repository=repository,
                        pull_request=pull_request,
                        delivery_id=delivery_id,
                        status="pending",
                        find_existing_pending=False,
                    )
        except Exception as e:
            logger.error(f"Failed to create pending Review record: {e}", exc_info=True)

        if commit:
            await session.commit()
        else:
            # Batched sync mode: leave the commit to the caller so the whole
            # repository batch (job + Pending Review rows for every PR)
            # becomes visible in one atomic commit.
            await session.flush()
        return job
    else:
        logger.info(
            f"Duplicate job ignored: delivery={delivery_id} sha={head_sha[:12]}"
        )
        return None


async def _supersede_inflight(
    session, db_pr, payload: dict[str, Any], new_sha: str
) -> None:
    """Cancel in-flight jobs and executions for a PR before a new commit run.

    The Review row itself is untouched here — it is reset by
    _reuse_latest_review_for_pr.
    """
    from app.models.review import Review
    from app.services.review_execution_service import cancel_active_executions

    await supersede_jobs(
        session, payload.get("repository", {}), db_pr.pr_number, new_sha
    )

    active_reviews = await session.execute(
        select(Review).where(
            Review.pr_id == db_pr.id,
            Review.status.in_(["queued", "pending", "running"]),
        )
    )
    for rev in active_reviews.scalars().all():
        await cancel_active_executions(session, rev.id)


async def _reuse_latest_review_for_pr(
    session,
    db_pr,
    payload: dict[str, Any],
    installation_id: int,
    head_sha: str,
    trigger: str = "webhook",
    commit: bool = True,
) -> None:
    """Reuse the latest Review row for a PR (reopened/synchronize/opened retry).

    Resets the row to 'pending' and creates a new ReviewExecution, so the PR
    keeps exactly ONE Review card across its whole lifecycle. If the PR has no
    Review row yet (the original opened event was missed), creates the initial
    Review as fallback.

    NOTE: error/summary/stats content lives on ReviewExecution rows, not on
    Review — the reviews table has no such columns, so only status/timestamps
    are reset here.
    """
    from app.models.review import Review
    from app.services.review_execution_service import (
        create_execution,
        get_latest_execution,
    )

    latest = await session.execute(
        select(Review)
        .where(Review.pr_id == db_pr.id)
        .order_by(Review.created_at.desc())
        .limit(1)
    )
    db_review = latest.scalars().first()

    if not db_review:
        db_review = Review(pr_id=db_pr.id, status="pending")
        session.add(db_review)
        await session.flush()
        logger.info(
            f"Created Review record {db_review.id} for PR #{db_pr.pr_number} "
            f"(fallback, trigger={trigger})"
        )

    # Idempotency: a redelivered webhook (new delivery_id, same sha/trigger)
    # must not stack a second queued execution onto the same Review.
    latest_exec = await get_latest_execution(session, db_review.id)
    if (
        latest_exec is not None
        and latest_exec.status in ("queued", "pending")
        and latest_exec.commit_sha == head_sha
        and latest_exec.trigger == trigger
    ):
        logger.info(
            f"Review {db_review.id} already has a queued '{trigger}' execution "
            f"for sha={head_sha[:12]} — not creating another one"
        )
        return

    db_review.status = "pending"
    db_review.started_at = None
    db_review.completed_at = None
    session.add(db_review)
    await session.flush()

    await create_execution(
        session, db_review.id, trigger=trigger, commit_sha=head_sha
    )
    if commit:
        await session.commit()
    else:
        await session.flush()
    logger.info(
        f"Reused Review {db_review.id} for {trigger} on PR #{db_pr.pr_number}"
    )


async def supersede_jobs(
    session,
    repository: dict[str, Any],
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
    from sqlalchemy import select as sel

    from app.models.github import Repository

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
        logger.info(
            f"Superseded {count} job(s) for PR #{pr_number} (new SHA: {new_sha[:12]})"
        )

    return count


async def get_pending_jobs(session, limit: int = 1) -> list[ReviewJob]:
    """Peek at pending jobs (inspection helper — takes NO locks).

    Returns the oldest queued job per repo ordered least-recently-completed
    first (same fairness ordering the worker uses when claiming). Claiming
    itself happens in the worker loop, which additionally takes the per-repo
    advisory lock plus the row lock.

    Args:
        session: Async database session.
        limit: Maximum number of jobs to fetch.

    Returns:
        List of queued ReviewJob records.
    """
    from sqlalchemy import text

    stmt = text(
        """
        WITH per_repo_next AS (
            SELECT j.id, j.repo_id, j.pr_number, j.head_sha, j.delivery_id, j.payload,
                   j.attempt_count, j.created_at,
                   ROW_NUMBER() OVER (PARTITION BY j.repo_id ORDER BY j.created_at ASC) as rn,
                   COALESCE((
                       SELECT MAX(completed_at)
                       FROM review_jobs r2
                       WHERE r2.repo_id = j.repo_id
                         AND r2.status = 'completed'
                   ), '1970-01-01'::timestamptz) as last_completed
            FROM review_jobs j
            WHERE j.status = 'queued'
              AND j.repo_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM review_jobs r
                  WHERE r.repo_id = j.repo_id
                    AND r.status = 'running'
              )
        )
        SELECT id, repo_id, pr_number, head_sha, delivery_id, payload,
               attempt_count, created_at
        FROM per_repo_next
        WHERE rn = 1
        ORDER BY last_completed ASC
        LIMIT :limit
    """
    )

    result = await session.execute(stmt, {"limit": limit})
    rows = result.fetchall()
    return rows


async def enqueue_lifecycle_job(
    session,
    payload: dict[str, Any],
    delivery_id: str,
    repo_id: UUID | None = None,
    pr_number: int | None = None,
    head_sha: str | None = None,
) -> ReviewJob | None:
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
    payload.get("installation", {})

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
        logger.info(
            f"Enqueued lifecycle job ({lifecycle_action}) {job.id} for PR #{target_pr_number}"
        )
        return job

    return None
