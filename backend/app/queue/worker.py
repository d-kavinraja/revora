"""Worker process for the review job queue."""

import asyncio
import logging
import signal
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy import text

from app.db.session import AsyncSessionLocal
from app.queue.models import ReviewJob, JobStatus

logger = logging.getLogger(__name__)

_worker_id = str(uuid.uuid4())[:8]
_shutdown = False


def _handle_shutdown(signum, frame):
    global _shutdown
    logger.info(f"Worker {_worker_id} received shutdown signal {signum}")
    _shutdown = True


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
        from app.pipeline.orchestrator import review_pipeline
        from app.github.auth import github_app_auth
        from app.github.webhooks import get_pr_diff
        from app.github.shared import resolve_provider_config, get_or_create_review_records
        from app.db.session import AsyncSessionLocal

        installation_id = payload["installation"]["id"]
        repository = payload["repository"]
        pull_request = payload["pull_request"]
        owner = repository["owner"]["login"]
        repo_name = repository["name"]
        pr_number = pull_request["number"]
        pr_title = pull_request["title"]
        pr_body = pull_request.get("body", "") or ""
        head_sha = pull_request["head"]["sha"]

        # Get installation token
        token = await github_app_auth.get_installation_token(installation_id)

        # Get diff content
        diff_content = await get_pr_diff(owner, repo_name, pr_number, token)

        # Create review records
        db_review, db_repo, db_pr, user_id = await get_or_create_review_records(
            installation_id, repository, pull_request, job_row[4], status="running"
        )

        # Resolve provider config
        async with AsyncSessionLocal() as db:
            provider, model, api_key_id = await resolve_provider_config(db, user_id, db_repo)

        # Build clone URL
        clone_url = f"https://github.com/{owner}/{repo_name}.git"

        # Execute the full pipeline
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
        )

        return result.get("status") == "success"

    except Exception as e:
        logger.error(f"Worker {_worker_id} job {job_id} failed: {e}", exc_info=True)
        try:
            from sqlalchemy import update
            from app.db.session import AsyncSessionLocal
            from app.models.github import PullRequest
            from app.models.review import Review
            
            repo_id = job_row[1]
            pr_num = job_row[2]
            
            async with AsyncSessionLocal() as db:
                pr_result = await db.execute(
                    select(PullRequest).where(
                        PullRequest.repo_id == repo_id,
                        PullRequest.pr_number == pr_num
                    )
                )
                db_pr = pr_result.scalars().first()
                if db_pr:
                    await db.execute(
                        update(Review)
                        .where(Review.pr_id == db_pr.id, Review.status == "pending")
                        .values(status="failed")
                    )
                    await db.commit()
        except Exception as inner_e:
            logger.error(f"Failed to update Review status to failed: {inner_e}")
            
        return False


async def run_worker(poll_interval: float = 2.0):
    """Main worker loop. Polls for queued jobs and processes them.

    Uses SELECT FOR UPDATE SKIP LOCKED for safe concurrent access.
    """
    logger.info(f"Worker {_worker_id} started (poll_interval={poll_interval}s)")

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    while not _shutdown:
        try:
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
                        started_at=datetime.now(timezone.utc),
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
                logger.info(f"Worker {_worker_id} job {job_id} was cancelled before processing started — skipping.")
                continue

            # Process the job as a task so we can cancel it
            job_task = asyncio.create_task(process_job(job_row))
            
            # Watcher task to poll for cancellation from the DB
            async def watch_for_cancellation(task: asyncio.Task, jid: uuid.UUID):
                while not task.done():
                    await asyncio.sleep(3)
                    try:
                        async with AsyncSessionLocal() as s:
                            res = await s.execute(select(ReviewJob).where(ReviewJob.id == jid))
                            job_status = res.scalars().first()
                            if job_status and job_status.status == JobStatus.CANCELLED:
                                logger.info(f"Worker {_worker_id} job {jid} cancelled by user during execution. Aborting...")
                                task.cancel()
                                break
                    except Exception as e:
                        pass # Ignore temporary DB errors in watcher
                        
            watcher_task = asyncio.create_task(watch_for_cancellation(job_task, job_id))

            try:
                success = await job_task
                new_status = JobStatus.COMPLETED if success else JobStatus.FAILED
            except asyncio.CancelledError:
                success = False
                new_status = JobStatus.CANCELLED
            finally:
                watcher_task.cancel()

            # Update status
            async with AsyncSessionLocal() as session:
                # Only update if we didn't just get cancelled (which is already set in DB)
                if new_status != JobStatus.CANCELLED:
                    await session.execute(
                        update(ReviewJob)
                        .where(ReviewJob.id == job_id)
                        .values(
                            status=new_status,
                            completed_at=datetime.now(timezone.utc),
                            attempt_count=job_row[6] + 1,
                        )
                    )
                else:
                    await session.execute(
                        update(ReviewJob)
                        .where(ReviewJob.id == job_id)
                        .values(
                            completed_at=datetime.now(timezone.utc),
                            attempt_count=job_row[6] + 1,
                        )
                    )
                await session.commit()

            logger.info(f"Worker {_worker_id} job {job_id} -> {new_status.value}")

        except Exception as e:
            logger.error(f"Worker {_worker_id} loop error: {e}", exc_info=True)
            await asyncio.sleep(poll_interval)

    logger.info(f"Worker {_worker_id} shut down gracefully")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())

