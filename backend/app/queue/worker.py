"""Worker process for the review job queue."""

import asyncio
import logging
import signal
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, select, text, update

from app.db.session import AsyncSessionLocal
from app.queue.models import JobStatus, ReviewJob

logger = logging.getLogger(__name__)

_worker_id = str(uuid.uuid4())[:8]
_shutdown = False


def _handle_shutdown(signum, frame):
    global _shutdown
    logger.info(f"Worker {_worker_id} received shutdown signal {signum}")
    _shutdown = True


def _extract_review_id(job) -> str | None:
    """Extract the review id from a job (ORM object or row tuple).

    Lifecycle jobs embed it in payload._lifecycle.new_review_id and in the
    delivery_id suffix ("{action}-{review_id}").
    """
    import json

    payload = getattr(job, "payload", None)
    if payload is None and isinstance(job, (tuple, list)) and len(job) > 5:
        payload = job[5]
    if payload is not None:
        try:
            if isinstance(payload, str):
                payload = json.loads(payload)
            lifecycle = payload.get("_lifecycle") or {}
            review_id = lifecycle.get("new_review_id")
            if review_id:
                uuid.UUID(review_id)
                return review_id
        except Exception:  # noqa: BLE001, S110
            pass

    delivery_id = getattr(job, "delivery_id", None)
    if delivery_id is None and isinstance(job, (tuple, list)) and len(job) > 4:
        delivery_id = job[4]
    if delivery_id:
        try:
            candidate = str(delivery_id).rsplit("-", 1)[1]
            uuid.UUID(candidate)
            return candidate
        except Exception:  # noqa: BLE001
            return None
    return None


async def _mark_review_failed(job, error_str: str):
    """Mark the job's review (and its latest execution) as failed."""
    from app.models.review import Review

    review_id = _extract_review_id(job)
    try:
        async with AsyncSessionLocal() as db:
            if review_id:
                await db.execute(
                    update(Review)
                    .where(Review.id == uuid.UUID(review_id))
                    .values(
                        status="failed",
                        error_message=error_str,
                        completed_at=datetime.now(UTC),
                    )
                )
                await db.commit()
            else:
                # Fall back to PR-scoped update (webhook jobs with no review link)
                from app.models.github import PullRequest

                pr_result = await db.execute(
                    select(PullRequest).where(
                        (
                            PullRequest.repo_id == job.repo_id
                            if hasattr(job, "repo_id")
                            else job[1]
                        ),
                        (
                            PullRequest.pr_number == job.pr_number
                            if hasattr(job, "pr_number")
                            else job[2]
                        ),
                    )
                )
                db_pr = pr_result.scalars().first()
                if db_pr:
                    await db.execute(
                        update(Review)
                        .where(Review.pr_id == db_pr.id)
                        .values(
                            status="failed",
                            error_message=error_str,
                            completed_at=datetime.now(UTC),
                        )
                    )
                    await db.commit()
            if review_id:
                from app.services.review_execution_service import mark_execution_final

                await mark_execution_final(db, uuid.UUID(review_id), "failed")
                await db.commit()
    except Exception as inner_e:  # noqa: BLE001
        logger.error(f"Failed to update Review status to failed: {inner_e}")


async def process_job(job_row) -> bool:
    """Process a single review job by invoking the orchestrator pipeline.

    Args:
        job_row: Row from SELECT FOR UPDATE SKIP LOCKED.

    Returns:
        True if job completed successfully, False otherwise.
    """
    job_id = job_row[0]
    payload = job_row[5]

    logger.info(f"Worker {_worker_id} processing job {job_id}")

    try:
        # Import the pipeline
        from app.db.session import AsyncSessionLocal
        from app.github.auth import github_app_auth
        from app.github.shared import (
            get_or_create_review_records,
            resolve_provider_config,
        )
        from app.github.webhooks import get_pr_diff
        from app.pipeline.orchestrator import review_pipeline

        installation = payload.get("installation", {}) or {}
        installation_id = installation.get("id")
        repository = payload.get("repository", {}) or {}
        pull_request = payload.get("pull_request", {}) or {}

        owner = repository.get("owner", {}).get("login", "")
        repo_name = repository.get("name", "")
        pr_number = pull_request.get("number", job_row[2])
        pr_title = pull_request.get("title", "Pull Request")
        pr_body = pull_request.get("body", "") or ""
        head_sha = pull_request.get("head", {}).get("sha", job_row[3])

        if not installation_id:
            raise ValueError(f"Missing installation_id in payload for job {job_id}")

        # Get installation token
        token = await github_app_auth.get_installation_token(installation_id)

        # Get diff content
        diff_content = await get_pr_diff(owner, repo_name, pr_number, token)

        # Re-check job status: the user may have cancelled this job while the
        # diff was being fetched (the claim → execution window spans seconds).
        async with AsyncSessionLocal() as status_db:
            check_result = await status_db.execute(
                select(ReviewJob).where(ReviewJob.id == job_id)
            )
            current_job = check_result.scalars().first()
        if current_job is None or current_job.status == JobStatus.CANCELLED:
            logger.info(
                f"Worker {_worker_id} job {job_id} was cancelled while in queue — skipping execution"
            )
            return False

        # Create review records (lifecycle jobs use their pre-created review)
        lifecycle = payload.get("_lifecycle", {}) or {}
        db_review, db_repo, _db_pr, user_id = await get_or_create_review_records(
            installation_id,
            repository,
            pull_request,
            job_row[4],
            status="running",
            existing_review_id=lifecycle.get("new_review_id"),
        )

        # Never run a pipeline for a review that was cancelled/failed meanwhile
        if db_review.status not in ("queued", "pending", "running"):
            logger.warning(
                f"Job {job_id} review {db_review.id} is already {db_review.status} — skipping execution"
            )
            return False

        # Resolve provider config — captures the config source for BYOK enforcement
        async with AsyncSessionLocal() as db:
            provider, model, api_key_id, config_source = await resolve_provider_config(
                db, user_id, db_repo
            )

        # MODE 3: Nothing configured — stop immediately with actionable error
        if config_source == "none" or not provider:
            error_msg = (
                "## AI Review could not start\n\n"
                "**Reason:** No AI configuration found for this repository.\n\n"
                "---\n\n"
                "### To fix this:\n\n"
                "1. **Add an API Key** in Settings > API Keys\n"
                "2. **Select a Provider and Model** in Repository Settings > Config\n"
                "3. **Re-run the Pull Request**\n\n"
                "---\n\n"
                "*If you continue to see this error, contact support.*"
            )
            logger.warning(f"MODE 3: No AI config for job {job_id}. PR #{pr_number}")
            try:
                from app.github.client import GitHubClient

                check_run = await GitHubClient().create_check_run(
                    installation_id=installation_id,
                    owner=owner,
                    repo=repo_name,
                    name="Revora AI Review",
                    head_sha=head_sha,
                    status="completed",
                    output={
                        "title": "AI Review could not start",
                        "summary": error_msg,
                        "conclusion": "failure",
                    },
                )
                logger.info(
                    f"Created failure check run for MODE 3: {check_run.get('id')}"
                )
            except Exception as e:  # noqa: BLE001
                logger.error(f"Failed to create MODE 3 check run: {e}")
            # Mark review as failed in DB
            try:
                async with AsyncSessionLocal() as db:
                    from sqlalchemy import update as sa_update

                    from app.models.review import Review

                    await db.execute(
                        sa_update(Review)
                        .where(Review.id == db_review.id)
                        .values(
                            status="failed",
                            error_message=error_msg,
                            completed_at=datetime.now(UTC),
                        )
                    )
                    from app.services.review_execution_service import (
                        mark_execution_final,
                    )

                    await mark_execution_final(db, db_review.id, "failed")
                    await db.commit()
            except Exception as e:  # noqa: BLE001
                logger.error(f"Failed to mark review as failed for MODE 3: {e}")
            return False

        # Build clone URL
        clone_url = f"https://github.com/{owner}/{repo_name}.git"

        # Log the execution mode
        mode_label = {
            "repo_config": "MODE 1 (Explicit Repo Config)",
            "user_routing": "MODE 2 (User Routing)",
        }.get(config_source, "UNKNOWN")
        logger.info(f"Execution mode: {mode_label} — {provider}/{model}")

        # Execute the full pipeline with immutable execution context
        result = await review_pipeline.execute(
            review_id=db_review.id,
            installation_id=installation_id,
            owner=owner,
            repo_name=repo_name,
            pr_number=pr_number,
            pr_title=pr_title,
            pr_description=pr_body,
            head_sha=head_sha,
            diff_content=diff_content,
            user_id=user_id,
            provider=provider,
            model=model,
            clone_url=clone_url,
            token=token,
            api_key_id=api_key_id,
            config_source=config_source,
        )

        return result.get("status") == "success"

    except Exception as e:
        logger.exception(f"Worker {_worker_id} job {job_id} failed")
        error_str = str(e) or f"Execution failed ({type(e).__name__})"
        await _mark_review_failed(job_row, error_str)
        return False


async def _fail_job_and_review(session, job, error_message: str):
    """Mark a job as failed and its associated review as failed."""
    from app.models.review import Review

    job.status = JobStatus.FAILED
    job.completed_at = datetime.now(UTC)
    job.error_text = error_message
    session.add(job)

    review_id = _extract_review_id(job)
    if review_id:
        await session.execute(
            update(Review)
            .where(Review.id == uuid.UUID(review_id))
            .values(
                status="failed",
                error_message=error_message,
                completed_at=datetime.now(UTC),
            )
        )
        from app.services.review_execution_service import mark_execution_final

        await mark_execution_final(session, uuid.UUID(review_id), "failed")
    else:
        from app.models.github import PullRequest

        pr_result = await session.execute(
            select(PullRequest).where(
                PullRequest.repo_id == job.repo_id,
                PullRequest.pr_number == job.pr_number,
            )
        )
        db_pr = pr_result.scalars().first()
        if db_pr:
            await session.execute(
                update(Review)
                .where(
                    Review.pr_id == db_pr.id,
                    Review.status.in_(["pending", "queued", "running"]),
                )
                .values(
                    status="failed",
                    error_message=error_message,
                    completed_at=datetime.now(UTC),
                )
            )


async def mark_review_cancelled(job_row, error_message: str = "Cancelled by user"):
    """Mark the review associated with a cancelled job as cancelled."""
    from app.models.review import Review

    review_id = _extract_review_id(job_row)
    if not review_id:
        # Webhook jobs carry no review link in delivery_id — cancel the PR's
        # active review(s) so a watcher-cancelled job never leaves a zombie
        # "running" review behind.
        try:
            repo_id = (
                getattr(job_row, "repo_id", None)
                if not isinstance(job_row, (tuple, list))
                else job_row[1]
            )
            pr_number = (
                getattr(job_row, "pr_number", None)
                if not isinstance(job_row, (tuple, list))
                else job_row[2]
            )
            if repo_id and pr_number:
                from app.models.github import PullRequest

                async with AsyncSessionLocal() as session:
                    pr_result = await session.execute(
                        select(PullRequest).where(
                            PullRequest.repo_id == repo_id,
                            PullRequest.pr_number == pr_number,
                        )
                    )
                    db_pr = pr_result.scalars().first()
                    if db_pr:
                        cancelled_result = await session.execute(
                            update(Review)
                            .where(
                                Review.pr_id == db_pr.id,
                                Review.status.in_(["queued", "pending", "running"]),
                            )
                            .values(status="cancelled", error_message=error_message)
                            .returning(Review.id)
                        )
                        from app.services.review_execution_service import (
                            mark_execution_final,
                        )

                        for rid in cancelled_result.scalars().all():
                            await mark_execution_final(session, rid, "cancelled")
                        await session.commit()
                        logger.info(
                            f"Marked PR #{pr_number} active review(s) as cancelled (job was cancelled)"
                        )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to cancel PR-scoped review for cancelled job: {e}")
        return
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(Review)
                .where(Review.id == uuid.UUID(review_id))
                .values(status="cancelled", error_message=error_message)
            )
            from app.services.review_execution_service import mark_execution_final

            await mark_execution_final(session, uuid.UUID(review_id), "cancelled")
            await session.commit()
            logger.info(f"Marked review {review_id} as cancelled (job was cancelled)")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Failed to mark review {review_id} as cancelled: {e}")


async def recover_orphaned_jobs(
    max_retries: int = 3,
    queue_timeout_minutes: int = 30,
    heartbeat_timeout_seconds: int = 120,
):
    """Detect and recover orphaned/stale jobs.

    Handles:
      - Jobs stuck in RUNNING (worker crashed mid-execution).
      - Jobs stuck in QUEUED beyond queue_timeout_minutes (worker never picked them up).
      - Jobs in RUNNING with stale heartbeat (watcher crashed but worker didn't).
    """
    now = datetime.now(UTC)
    try:
        async with AsyncSessionLocal() as session:
            # --- Recover stale RUNNING jobs (original logic + heartbeat check) ---
            running_result = await session.execute(
                select(ReviewJob).where(
                    and_(
                        ReviewJob.status == JobStatus.RUNNING,
                        ReviewJob.updated_at
                        < now - timedelta(seconds=heartbeat_timeout_seconds),
                    )
                )
            )
            stale_running = running_result.scalars().all()

            # --- Recover stale QUEUED jobs ---
            queued_result = await session.execute(
                select(ReviewJob).where(
                    and_(
                        ReviewJob.status == JobStatus.QUEUED,
                        ReviewJob.created_at
                        < now - timedelta(minutes=queue_timeout_minutes),
                    )
                )
            )
            stale_queued = queued_result.scalars().all()

            if not stale_running and not stale_queued:
                return

            logger.info(
                f"Crash Recovery: Found {len(stale_running)} stale running job(s) "
                f"and {len(stale_queued)} stale queued job(s)."
            )

            # Process stale QUEUED jobs (mark as failed immediately — timeout)
            for job in stale_queued:
                await _fail_job_and_review(
                    session,
                    job,
                    f"Job timed out in queue after {queue_timeout_minutes} minutes.",
                )
                logger.warning(
                    f"Crash Recovery: Stale queued job {job.id} for PR #{job.pr_number} "
                    f"timed out after {queue_timeout_minutes} min. Marked as failed."
                )

            # Process stale RUNNING jobs (original recovery logic)
            for job in stale_running:
                if job.attempt_count < max_retries:
                    job.attempt_count += 1
                    job.status = JobStatus.QUEUED
                    job.worker_id = None
                    session.add(job)

                    from app.models.github import PullRequest
                    from app.models.review import Review

                    pr_result = await session.execute(
                        select(PullRequest).where(
                            PullRequest.repo_id == job.repo_id,
                            PullRequest.pr_number == job.pr_number,
                        )
                    )
                    db_pr = pr_result.scalars().first()
                    if db_pr:
                        await session.execute(
                            update(Review)
                            .where(
                                Review.pr_id == db_pr.id,
                                Review.status.in_(["pending", "running"]),
                            )
                            .values(status="pending")
                        )
                    review_id = _extract_review_id(job)
                    if review_id:
                        from app.services.review_execution_service import (
                            get_latest_execution,
                        )

                        execution = await get_latest_execution(
                            session, uuid.UUID(review_id)
                        )
                        if execution and execution.status == "running":
                            execution.status = "queued"
                            session.add(execution)
                    logger.info(
                        f"Crash Recovery: Re-queued stale running job {job.id} for PR #{job.pr_number} "
                        f"(Attempt {job.attempt_count}/{max_retries})."
                    )
                else:
                    await _fail_job_and_review(
                        session,
                        job,
                        "Server restarted mid-review; retry limit reached.",
                    )
                    logger.warning(
                        f"Crash Recovery: Job {job.id} for PR #{job.pr_number} "
                        f"exceeded max retries. Marked as failed."
                    )

            await session.commit()
    except Exception:
        logger.exception("Error during orphaned job recovery")


async def run_worker(poll_interval: float = 2.0, standalone: bool = True):
    """Main worker loop. Polls for queued jobs and processes them.

    Uses SELECT FOR UPDATE SKIP LOCKED for safe concurrent access.
    """
    logger.info(f"Worker {_worker_id} started (poll_interval={poll_interval}s)")

    if standalone:
        signal.signal(signal.SIGINT, _handle_shutdown)
        signal.signal(signal.SIGTERM, _handle_shutdown)

    # Recover any jobs left in 'running' status from a previous server crash
    await recover_orphaned_jobs()

    last_recovery_check = datetime.now(UTC)

    while not _shutdown:
        try:
            # Periodically check for stale/orphaned jobs every 60s
            if (datetime.now(UTC) - last_recovery_check).total_seconds() > 60:
                await recover_orphaned_jobs()
                last_recovery_check = datetime.now(UTC)

            async with AsyncSessionLocal() as session:
                # Fetch one queued job with row-level locking
                stmt = text("""
                    SELECT id, repo_id, pr_number, head_sha, delivery_id, payload,
                           attempt_count, created_at
                    FROM review_jobs
                    WHERE status = 'queued'
                    ORDER BY created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                """)
                result = await session.execute(stmt)
                job_row = result.fetchone()

                if not job_row:
                    await asyncio.sleep(poll_interval)
                    continue

                job_id = job_row[0]

                # Mark as running
                await session.execute(
                    update(ReviewJob)
                    .where(ReviewJob.id == job_id)
                    .values(
                        status=JobStatus.RUNNING,
                        started_at=datetime.now(UTC),
                        worker_id=_worker_id,
                    )
                )
                await session.commit()

            # Process outside the session lock — but first re-check status in case
            # it was cancelled by the user between being claimed and execution starting.
            async with AsyncSessionLocal() as check_session:
                check_result = await check_session.execute(
                    select(ReviewJob).where(ReviewJob.id == job_id)
                )
                current_job = check_result.scalars().first()

            if current_job and current_job.status == JobStatus.CANCELLED:
                logger.info(
                    f"Worker {_worker_id} job {job_id} was cancelled before processing started — skipping."
                )
                continue

            # Process the job as a task so we can cancel it
            job_task = asyncio.create_task(process_job(job_row))

            # Watcher task to poll for cancellation and update heartbeat timestamp
            async def watch_for_cancellation(task: asyncio.Task, jid: uuid.UUID):
                while not task.done():
                    await asyncio.sleep(5)
                    try:
                        async with AsyncSessionLocal() as s:
                            res = await s.execute(
                                select(ReviewJob).where(ReviewJob.id == jid)
                            )
                            job_status = res.scalars().first()
                            if job_status and job_status.status == JobStatus.CANCELLED:
                                logger.info(
                                    f"Worker {_worker_id} job {jid} cancelled by user during execution. Aborting..."
                                )
                                task.cancel()
                                break
                            elif job_status:
                                job_status.updated_at = datetime.now(UTC)
                                s.add(job_status)
                                await s.commit()
                    except Exception:  # noqa: BLE001, S110
                        pass  # Ignore temporary DB errors in watcher

            watcher_task = asyncio.create_task(watch_for_cancellation(job_task, job_id))

            try:
                success = await job_task
                new_status = JobStatus.COMPLETED if success else JobStatus.FAILED
            except asyncio.CancelledError:
                success = False
                new_status = JobStatus.CANCELLED
                # Ensure the review row is marked cancelled too, so the
                # "active review" lock is released (never leave zombies).
                await mark_review_cancelled(job_row)
            finally:
                watcher_task.cancel()

            # Update status
            async with AsyncSessionLocal() as session:
                # Preserve a user-initiated cancellation: a job cancelled in the
                # DB (cancel_review) must not be overwritten with FAILED when the
                # process_job guard bails out after the cancellation landed.
                if new_status != JobStatus.CANCELLED:
                    cur_result = await session.execute(
                        select(ReviewJob).where(ReviewJob.id == job_id)
                    )
                    cur_job = cur_result.scalars().first()
                    if cur_job and cur_job.status == JobStatus.CANCELLED:
                        new_status = JobStatus.CANCELLED

                if new_status != JobStatus.CANCELLED:
                    await session.execute(
                        update(ReviewJob)
                        .where(ReviewJob.id == job_id)
                        .values(
                            status=new_status,
                            completed_at=datetime.now(UTC),
                            attempt_count=job_row[6] + 1,
                        )
                    )
                else:
                    await session.execute(
                        update(ReviewJob)
                        .where(ReviewJob.id == job_id)
                        .values(
                            completed_at=datetime.now(UTC),
                            attempt_count=job_row[6] + 1,
                        )
                    )
                await session.commit()

            import gc

            gc.collect()

            logger.info(f"Worker {_worker_id} job {job_id} -> {new_status.value}")

        except Exception:
            logger.exception(f"Worker {_worker_id} loop error")
            await asyncio.sleep(poll_interval)

    logger.info(f"Worker {_worker_id} shut down gracefully")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())
