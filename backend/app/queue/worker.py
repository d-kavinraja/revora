"""Worker process for the review job queue."""

import asyncio
import logging
import signal
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, select, text, update

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.queue.models import JobStatus, ReviewJob
from app.security.error_sanitizer import sanitize_error_message
from app.services.installation_lifecycle import require_attemptable_installation
from app.services.platform_settings import platform_settings_service

logger = logging.getLogger(__name__)

_worker_id = str(uuid.uuid4())[:8]
_shutdown = False

# The global single-flight review advisory lock is intentionally removed:
# review execution is now bounded by REVIEW_WORKER_CONCURRENCY per process and
# safe across processes via atomic SELECT ... FOR UPDATE SKIP LOCKED claiming
# plus per-repository hashtext() transaction-scoped locks (which serialize
# same-repository jobs). See REVIEW_WORKER_CONCURRENCY in app/core/config.py.

# Serializes claim attempts inside one process (uvicorn + accidental second
# loop) so the fair-ordering query never races itself. Cross-process safety
# comes from the per-repo advisory lock and FOR UPDATE SKIP LOCKED.
_claim_slot = asyncio.Lock()

# Worker-liveness signals for queue recovery (P0-2). They distinguish a
# healthy queued backlog (worker alive and draining, or single-flight
# legitimately holding jobs behind a running one) from a genuinely stuck
# worker that will never claim anything again.
_worker_started_at: datetime | None = None
_last_claim_at: datetime | None = None


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
        except Exception:
            pass

    delivery_id = getattr(job, "delivery_id", None)
    if delivery_id is None and isinstance(job, (tuple, list)) and len(job) > 4:
        delivery_id = job[4]
    if delivery_id:
        try:
            candidate = str(delivery_id).rsplit("-", 1)[1]
            uuid.UUID(candidate)
            return candidate
        except Exception:
            return None
    return None


async def _mark_review_failed(job, error_str: str):
    """Mark the job's review (and its latest execution) as failed.

    NOTE: the reviews table holds only status/timestamps — error detail lives
    on the ReviewExecution row (reviews has no error_message column).
    """
    from app.models.review import Review

    error_str = sanitize_error_message(error_str)
    review_id = _extract_review_id(job)
    try:
        async with AsyncSessionLocal() as db:
            from app.services.review_execution_service import (
                ensure_execution,
                mark_execution_final,
            )

            if review_id:
                await db.execute(
                    update(Review)
                    .where(Review.id == uuid.UUID(review_id))
                    .values(
                        status="failed",
                        completed_at=datetime.now(UTC),
                    )
                )
                await ensure_execution(db, uuid.UUID(review_id))
                await mark_execution_final(
                    db, uuid.UUID(review_id), "failed", error_message=error_str
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
                    failed_ids = (
                        await db.execute(
                            update(Review)
                            .where(
                                Review.pr_id == db_pr.id,
                                Review.status.in_(
                                    ["queued", "pending", "running"]
                                ),
                            )
                            .values(
                                status="failed",
                                completed_at=datetime.now(UTC),
                            )
                            .returning(Review.id)
                        )
                    ).scalars().all()
                    for rid in failed_ids:
                        await ensure_execution(db, rid)
                        await mark_execution_final(
                            db, rid, "failed", error_message=error_str
                        )
                    await db.commit()
    except Exception as inner_e:
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
        from app.github.auth import github_app_auth
        from app.github.errors import GitHubAuthError
        from app.github.shared import (
            get_or_create_review_records,
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

        # Get installation token. Fail closed: a missing local installation
        # row is just as untrusted as a suspended one — never fall through to
        # a token request for unknown installations.
        async with AsyncSessionLocal() as install_db:
            await require_attemptable_installation(install_db, installation_id)
        try:
            token = await github_app_auth.get_installation_token(installation_id)
        except GitHubAuthError as exc:
            raise RuntimeError(
                f"GitHub installation {installation_id} authentication failed: {exc.category}"
            ) from exc

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

        # Resolve provider config — captures the config source for BYOK enforcement.
        # A selection snapshot written at enqueue time is authoritative for this
        # execution; only resolve again when no snapshot exists (legacy rows) or
        # the snapshot could not resolve a model.
        from app.services.review_execution_service import (
            get_latest_execution,
            mark_execution_running,
        )
        from app.services.review_selection import (
            apply_selection_to_execution,
            read_selection_snapshot,
            resolve_selection,
            selection_from_snapshot,
            validate_selection,
        )
        from app.services.provider_registry import ProviderUnavailableError

        fallback_routes = None
        async with AsyncSessionLocal() as db:
            current_execution = await get_latest_execution(db, db_review.id)
            snapshot = read_selection_snapshot(current_execution)
            if snapshot and current_execution is not None:
                selection = await resolve_selection(db, user_id, db_repo)
                if selection.is_resolved:
                    try:
                        await validate_selection(db, selection)
                    except ProviderUnavailableError:
                        # The saved primary became unavailable after enqueue.
                        # Re-resolve primary-first; the repository's fallback
                        # preference is applied inside resolve_selection.
                        selection = await resolve_selection(db, user_id, db_repo)
                        apply_selection_to_execution(current_execution, selection)
                        db.add(current_execution)
                if not selection.is_resolved:
                    selection = await resolve_selection(db, user_id, db_repo)
                    apply_selection_to_execution(current_execution, selection)
                    db.add(current_execution)
            else:
                selection = await resolve_selection(db, user_id, db_repo)
                if current_execution is not None:
                    apply_selection_to_execution(current_execution, selection)
                    db.add(current_execution)

            # Repository fallback: when the repository opted in, prepare the
            # existing ModelRouter's ranked alternatives (excluding the primary)
            # for inference-time fallback. MODE 2 (no repo mapping) keeps its
            # historical same-provider retry behavior.
            if selection.is_resolved and db_repo is not None:
                repo_settings = dict(db_repo.settings or {})
                if repo_settings.get("fallback_enabled"):
                    try:
                        from app.orchestrator.models import FallbackRoute
                        from app.services.model_router import model_router

                        routes = await model_router.route(
                            db, uuid.UUID(str(user_id)), "code_review"
                        )
                        fallback_routes = [
                            FallbackRoute(
                                provider=r.provider,
                                model=r.model,
                                api_key_id=r.api_key_id,
                            )
                            for r in routes
                            if (r.provider, r.model)
                            != (selection.provider, selection.model)
                        ][:2]
                    except Exception as route_e:
                        logger.warning(
                            f"Fallback route discovery failed for review {db_review.id}: {route_e}"
                        )
                        fallback_routes = None
            await db.commit()

        provider = selection.provider
        model = selection.model
        api_key_id = selection.api_key_id
        config_source = selection.source

        # MODE 3 / unresolved: Nothing configured — stop immediately with an
        # actionable error. Never execute with a model that was not resolved.
        if not selection.is_resolved:
            error_msg = (
                sanitize_error_message(selection.error)
                if selection.error
                else (
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
            except Exception as e:
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
                            completed_at=datetime.now(UTC),
                        )
                    )
                    from app.services.review_execution_service import (
                        ensure_execution,
                        mark_execution_final,
                    )

                    await ensure_execution(db, db_review.id)
                    await mark_execution_final(
                        db, db_review.id, "failed", error_message=error_msg
                    )
                    await db.commit()
            except Exception as e:
                logger.error(f"Failed to mark review as failed for MODE 3: {e}")
            return False

        # Build clone URL
        clone_url = f"https://github.com/{owner}/{repo_name}.git"

        # The selection is valid and the pipeline is about to start: transition
        # the execution to running so the UI reports an honest status before
        # completion. Only actual execution attempts reach this point.
        try:
            async with AsyncSessionLocal() as db:
                await mark_execution_running(db, db_review.id)
                await db.commit()
        except Exception as e:
            logger.warning(f"Failed to mark execution running for {db_review.id}: {e}")

        # Log the execution mode
        mode_label = {
            "repo_config": "MODE 1 (Explicit Repo Config)",
            "user_routing": "MODE 2 (User Routing)",
        }.get(config_source, "UNKNOWN")
        logger.info(f"Execution mode: {mode_label} — {provider}/{model}")

        # Explicit cancellation check used before each LLM/fallback attempt so a
        # cancelled review can never start another inference. The worker task
        # watcher remains the primary cancellation mechanism.
        async def _is_cancelled() -> bool:
            try:
                async with AsyncSessionLocal() as _cdb:
                    from app.models.review import Review

                    _res = await _cdb.execute(
                        select(Review).where(Review.id == db_review.id)
                    )
                    _review = _res.scalars().first()
                    if _review is not None and _review.status == "cancelled":
                        return True
                    _jres = await _cdb.execute(
                        select(ReviewJob).where(ReviewJob.id == job_id)
                    )
                    _job = _jres.scalars().first()
                    if _job is not None and _job.status == JobStatus.CANCELLED:
                        return True
            except Exception:
                pass
            return False

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
            fallback_routes=fallback_routes,
            cancel_check=_is_cancelled,
        )

        return result.get("status") == "success"

    except Exception as e:
        logger.exception(f"Worker {_worker_id} job {job_id} failed")
        error_str = sanitize_error_message(
            str(e) or f"Execution failed ({type(e).__name__})"
        )
        await _mark_review_failed(job_row, error_str)
        return False


async def _fail_job_and_review(session, job, error_message: str):
    """Mark a job as failed and its associated review as failed."""
    error_message = sanitize_error_message(error_message)
    from app.models.review import Review

    job.status = JobStatus.FAILED
    job.completed_at = datetime.now(UTC)
    job.error_text = error_message
    session.add(job)

    from app.services.review_execution_service import (
        ensure_execution,
        mark_execution_final,
    )

    review_id = _extract_review_id(job)
    if review_id:
        await session.execute(
            update(Review)
            .where(Review.id == uuid.UUID(review_id))
            .values(
                status="failed",
                completed_at=datetime.now(UTC),
            )
        )
        await ensure_execution(session, uuid.UUID(review_id))
        await mark_execution_final(
            session, uuid.UUID(review_id), "failed", error_message=error_message
        )
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
            failed_ids = (
                await session.execute(
                    update(Review)
                    .where(
                        Review.pr_id == db_pr.id,
                        Review.status.in_(["pending", "queued", "running"]),
                    )
                    .values(
                        status="failed",
                        completed_at=datetime.now(UTC),
                    )
                    .returning(Review.id)
                )
            ).scalars().all()
            for rid in failed_ids:
                await ensure_execution(session, rid)
                await mark_execution_final(
                    session, rid, "failed", error_message=error_message
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
                            .values(status="cancelled")
                            .returning(Review.id)
                        )
                        from app.services.review_execution_service import (
                            mark_execution_final,
                        )

                        for rid in cancelled_result.scalars().all():
                            await mark_execution_final(
                                session,
                                rid,
                                "cancelled",
                                error_message=error_message,
                            )
                        await session.commit()
                        logger.info(
                            f"Marked PR #{pr_number} active review(s) as cancelled (job was cancelled)"
                        )
        except Exception as e:
            logger.warning(f"Failed to cancel PR-scoped review for cancelled job: {e}")
        return
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(Review)
                .where(Review.id == uuid.UUID(review_id))
                .values(status="cancelled")
            )
            from app.services.review_execution_service import mark_execution_final

            await mark_execution_final(
                session,
                uuid.UUID(review_id),
                "cancelled",
                error_message=error_message,
            )
            await session.commit()
            logger.info(f"Marked review {review_id} as cancelled (job was cancelled)")
    except Exception as e:
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

            # Healthy-backlog guard: a QUEUED job is only a recovery candidate
            # when the queue is provably stuck — no RUNNING job anywhere (a
            # running job legitimately holds its repo's siblings behind the
            # per-repo single-flight, and a draining serial worker holds
            # everyone else's) AND this worker has claimed nothing within the
            # timeout window. Otherwise the jobs are simply waiting their
            # turn and must be left alone to drain.
            skip_queued_timeout = False
            skip_reason = ""
            running_count = (
                await session.execute(
                    select(func.count())
                    .select_from(ReviewJob)
                    .where(ReviewJob.status == JobStatus.RUNNING)
                )
            ).scalar() or 0
            if running_count:
                skip_queued_timeout = True
                skip_reason = (
                    f"{running_count} job(s) currently running — "
                    "queued jobs are waiting behind them, not orphaned"
                )
            elif _worker_started_at is not None and (
                now - _worker_started_at
            ) < timedelta(minutes=queue_timeout_minutes):
                skip_queued_timeout = True
                skip_reason = (
                    "worker started recently — giving the loop a chance "
                    "to claim queued jobs first"
                )
            elif _last_claim_at is not None and (now - _last_claim_at) < timedelta(
                minutes=queue_timeout_minutes
            ):
                skip_queued_timeout = True
                skip_reason = (
                    "worker claimed a job recently — queue is draining, "
                    "not stuck"
                )
            if skip_queued_timeout:
                logger.info(
                    f"Crash Recovery: keeping {len(stale_queued)} stale "
                    f"queued job(s) queued ({skip_reason})."
                )
                stale_queued = []

            # Process stale QUEUED jobs (mark as failed immediately — timeout).
            # Per-job isolation: one bad job is logged + persisted, then the
            # pass continues with the remaining jobs (never aborts globally).
            for job in stale_queued:
                job_id, pr_number = job.id, job.pr_number
                try:
                    await _fail_job_and_review(
                        session,
                        job,
                        f"Job timed out in queue after {queue_timeout_minutes} minutes.",
                    )
                    await session.commit()
                    logger.warning(
                        f"Crash Recovery: Stale queued job {job_id} for PR #{pr_number} "
                        f"timed out after {queue_timeout_minutes} min. Marked as failed."
                    )
                except Exception as job_e:
                    await session.rollback()
                    logger.error(
                        f"Crash Recovery: failed to fail stale queued job "
                        f"{job_id} (PR #{pr_number}): {job_e}",
                        exc_info=True,
                    )

            # Process stale RUNNING jobs (original recovery logic)
            for job in stale_running:
                job_id, pr_number = job.id, job.pr_number
                try:
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
                        await session.commit()
                        logger.info(
                            f"Crash Recovery: Re-queued stale running job {job_id} for PR #{pr_number} "
                            f"(Attempt {job.attempt_count}/{max_retries})."
                        )
                    else:
                        await _fail_job_and_review(
                            session,
                            job,
                            "Server restarted mid-review; retry limit reached.",
                        )
                        await session.commit()
                        logger.warning(
                            f"Crash Recovery: Job {job_id} for PR #{pr_number} "
                            f"exceeded max retries. Marked as failed."
                        )
                except Exception as job_e:
                    await session.rollback()
                    logger.error(
                        f"Crash Recovery: failed to recover stale running job "
                        f"{job_id} (PR #{pr_number}): {job_e}",
                        exc_info=True,
                    )
    except Exception:
        logger.exception("Error during orphaned job recovery")


def _is_postgres(session) -> bool:
    try:
        return session.get_bind().dialect.name == "postgresql"
    except Exception:
        return False


async def _acquire_global_claim_lock(session) -> bool:
    """Compatibility shim for older call sites (returns True unconditionally)."""
    return True


async def claim_next_job(session) -> tuple | None:
    """Claim exactly one queued review job atomically.

    Concurrency model:
      - GLOBAL: bounded by REVIEW_WORKER_CONCURRENCY per process (cross-process
        claim safety via FOR UPDATE SKIP LOCKED; slots are counted per process).
      - PER-REPO: at most one RUNNING job per repository (hashtext xact lock).
      - Fairness: least-recently-completed repo first, then oldest job
        (per-repo FIFO preserved).
    """
    async with _claim_slot:
        return await _claim_next_job_locked(session)


async def claim_next_job_with_factory(session_factory) -> tuple | None:
    """Like claim_next_job, but opens the session AFTER the claim slot lock.

    Safe under concurrent callers with a StaticPool SQLite test engine
    (only one DB connection exists; serializing open→claim avoids checkout
    races). Production uses claim_next_job(session) from run_worker.
    """
    async with _claim_slot, session_factory() as session:
        return await _claim_next_job_locked(session)


async def _claim_next_job_locked(session) -> tuple | None:
    # Maintenance gate (§12.3): stop claiming NEW jobs while enabled. Queued
    # jobs persist untouched and resume on disable; in-flight runs are
    # unaffected (the worker loop only consults this before claiming).
    if await platform_settings_service.is_enabled(session):
        await session.rollback()
        return None

    # The global single-flight lock and per-repository serialization were
    # intentionally removed. Claiming is safe for bounded concurrency: atomic
    # transaction-scoped claims use FOR UPDATE SKIP LOCKED, and jobs from any
    # repository — including the same repository — may occupy distinct slots.
    # Slots are counted by the run_worker() loop / REVIEW_WORKER_CONCURRENCY.
    # Fairness: prefer the repository with the fewest running jobs, then
    # least-recently-completed, then oldest queued job.
    pg = _is_postgres(session)
    ts_fallback = "'1970-01-01'::timestamptz" if pg else "'1970-01-01'"
    order_res = await session.execute(
        text(
            f"""
            WITH per_repo AS (
                SELECT j.repo_id,
                       MIN(j.created_at) AS oldest,
                       COALESCE((
                           SELECT MAX(completed_at)
                           FROM review_jobs r2
                           WHERE r2.repo_id = j.repo_id
                             AND r2.status = 'completed'
                       ), {ts_fallback}) AS last_completed,
                       (
                           SELECT COUNT(*)
                           FROM review_jobs r_running
                           WHERE r_running.repo_id = j.repo_id
                             AND r_running.status = 'running'
                       ) AS running_count
                FROM review_jobs j
                WHERE j.status = 'queued'
                  AND j.repo_id IS NOT NULL
                GROUP BY j.repo_id
                UNION ALL
                SELECT NULL AS repo_id,
                       MIN(j.created_at) AS oldest,
                       MIN(j.created_at) AS last_completed,
                       (
                           SELECT COUNT(*)
                           FROM review_jobs r_running
                           WHERE r_running.repo_id IS NULL
                             AND r_running.status = 'running'
                       ) AS running_count
                FROM review_jobs j
                WHERE j.status = 'queued'
                  AND j.repo_id IS NULL
            )
            SELECT repo_id FROM per_repo
            ORDER BY running_count ASC, last_completed ASC, oldest ASC
            """
        )
    )
    candidate_repos = [row[0] for row in order_res.fetchall()]

    job_row = None
    for candidate_repo_id in candidate_repos:
        if candidate_repo_id is None:
            claim = await session.execute(
                text(
                    """
                    SELECT j.id, j.repo_id, j.pr_number, j.head_sha,
                           j.delivery_id, j.payload,
                           j.attempt_count, j.created_at
                    FROM review_jobs j
                    WHERE j.status = 'queued'
                      AND j.repo_id IS NULL
                    ORDER BY j.created_at ASC
                    LIMIT 1
                    """
                    + ("\nFOR UPDATE SKIP LOCKED" if pg else "")
                )
            )
        else:
            claim = await session.execute(
                text(
                    """
                    SELECT j.id, j.repo_id, j.pr_number, j.head_sha,
                           j.delivery_id, j.payload,
                           j.attempt_count, j.created_at
                    FROM review_jobs j
                    WHERE j.status = 'queued'
                      AND j.repo_id = :repo_id
                    ORDER BY j.created_at ASC
                    LIMIT 1
                    """
                    + ("\nFOR UPDATE SKIP LOCKED" if pg else "")
                ),
                {"repo_id": candidate_repo_id},
            )
        job_row = claim.fetchone()
        if job_row is not None:
            break

    if not job_row:
        await session.rollback()
        return None

    # Raw text() returns UUIDs as hex strings; coerce for the UUID column.
    claimed_id = job_row[0]
    if isinstance(claimed_id, str):
        claimed_id = uuid.UUID(claimed_id)
    normalized = list(job_row)
    normalized[0] = claimed_id
    if normalized[1] is not None and isinstance(normalized[1], str):
        normalized[1] = uuid.UUID(normalized[1])
    job_row = tuple(normalized)

    await session.execute(
        update(ReviewJob)
        .where(ReviewJob.id == claimed_id)
        .values(
            status=JobStatus.RUNNING,
            started_at=datetime.now(UTC),
            worker_id=_worker_id,
        )
    )
    await session.commit()
    return job_row


async def _execute_claimed_job(job_row, worker_id: str) -> None:
    """Run one claimed job to completion inside its own supervised task.

    Keeps the job lifecycle semantics of the original serial loop: cancel
    re-check, cancellation watcher, status transition to COMPLETED / FAILED /
    CANCELLED, and orphan-recovery-compatible heartbeat updates.
    """
    job_id = job_row[0]
    try:
        async with AsyncSessionLocal() as check_session:
            check_result = await check_session.execute(
                select(ReviewJob).where(ReviewJob.id == job_id)
            )
            current_job = check_result.scalars().first()
        if current_job and current_job.status == JobStatus.CANCELLED:
            logger.info(
                f"Worker {worker_id} job {job_id} was cancelled before processing started - skipping."
            )
            return

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
                                f"Worker {worker_id} job {jid} cancelled by user during execution. Aborting..."
                            )
                            task.cancel()
                            break
                        elif job_status:
                            job_status.updated_at = datetime.now(UTC)
                            s.add(job_status)
                            await s.commit()
                except Exception:
                    pass  # Ignore temporary DB errors in watcher

        job_task = asyncio.create_task(process_job(job_row))
        watcher_task = asyncio.create_task(watch_for_cancellation(job_task, job_id))

        try:
            success = await job_task
            new_status = JobStatus.COMPLETED if success else JobStatus.FAILED
        except asyncio.CancelledError:
            new_status = JobStatus.CANCELLED
            await mark_review_cancelled(job_row)
        finally:
            watcher_task.cancel()

        async with AsyncSessionLocal() as session:
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

        logger.info(f"Worker {worker_id} job {job_id} -> {new_status.value}")
    except asyncio.CancelledError:
        try:
            await mark_review_cancelled(job_row)
        except Exception:
            logger.warning(
                f"Worker {worker_id} could not mark job {job_id} cancelled during shutdown"
            )
        raise
    except Exception:
        logger.exception(f"Worker {worker_id} job {job_id} failed to execute")


async def run_worker(
    poll_interval: float | None = None,
    standalone: bool = True,
    concurrency: int | None = None,
):
    """Main worker loop. Polls for queued jobs and processes them concurrently.

    Bounded execution: at most REVIEW_WORKER_CONCURRENCY (default 1, max 5)
    jobs run at once. Claims happen only while a slot is free, so a worker
    never claims more jobs than it can execute. Cross-process workers are safe
    via FOR UPDATE SKIP LOCKED and per-repository hashtext() transaction
    locks. Fairness is least-recently-completed repo first, then oldest job.
    """
    global _worker_started_at, _last_claim_at

    if concurrency is None:
        concurrency = getattr(settings, "REVIEW_WORKER_CONCURRENCY", 1) or 1
    concurrency = max(1, min(5, int(concurrency)))
    if poll_interval is None:
        poll_interval = getattr(
            settings, "REVIEW_WORKER_POLL_INTERVAL_SECONDS", 2.0
        ) or 2.0
    shutdown_timeout = (
        getattr(settings, "REVIEW_WORKER_SHUTDOWN_TIMEOUT_SECONDS", 300) or 300
    )

    logger.info(
        f"Worker {_worker_id} started (poll_interval={poll_interval}s, concurrency={concurrency})"
    )

    if standalone:
        signal.signal(signal.SIGINT, _handle_shutdown)
        signal.signal(signal.SIGTERM, _handle_shutdown)

    _worker_started_at = datetime.now(UTC)
    await recover_orphaned_jobs()
    last_recovery_check = datetime.now(UTC)
    running: set[asyncio.Task] = set()

    while not _shutdown:
        try:
            now = datetime.now(UTC)
            if (now - last_recovery_check).total_seconds() > 60:
                await recover_orphaned_jobs()
                last_recovery_check = now

            # Reap finished execution tasks and surface unexpected failures.
            finished = [t for t in running if t.done()]
            for t in finished:
                running.discard(t)
                if not t.cancelled():
                    exc = t.exception()
                    if exc:
                        logger.exception(
                            f"Worker {_worker_id} execution task crashed",
                            exc_info=exc,
                        )

            # Fill free slots with newly claimed jobs.
            made_progress = False
            while len(running) < concurrency and not _shutdown:
                async with AsyncSessionLocal() as session:
                    job_row = await claim_next_job(session)
                if not job_row:
                    break
                _last_claim_at = datetime.now(UTC)
                task = asyncio.create_task(_execute_claimed_job(job_row, _worker_id))
                running.add(task)
                made_progress = True

            if not running:
                await asyncio.sleep(poll_interval)
            elif not made_progress and len(running) >= concurrency:
                # Slots full and no claim progress: wait for one to finish
                # instead of polling tags.
                await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            else:
                await asyncio.sleep(poll_interval)
        except Exception:
            logger.exception(f"Worker {_worker_id} loop error")
            await asyncio.sleep(poll_interval)

    logger.info(f"Worker {_worker_id} shutting down (active={len(running)})")
    for t in running:
        t.cancel()
    if running:
        _, pending = await asyncio.wait(running, timeout=shutdown_timeout)
        if pending:
            logger.warning(
                f"Worker {_worker_id} shutdown exceeded {shutdown_timeout}s with {len(pending)} active task(s)"
            )
    try:
        await recover_orphaned_jobs()
    except Exception:
        logger.exception(f"Worker {_worker_id} shutdown recovery failed")

    logger.info(f"Worker {_worker_id} shut down gracefully")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())
