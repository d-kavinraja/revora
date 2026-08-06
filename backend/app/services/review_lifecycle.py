"""ReviewLifecycleService — review retry, restart, rerun, and cancel operations.

One Review row per pull request lifecycle: rerun/retry/restart REUSE the
existing review row (status/summary updated in place). Each run is tracked
as a ReviewExecution row for history.
"""

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.exec_context import ReviewExecutionContext
from app.models.github import Installation, PullRequest, Repository
from app.models.review import Review
from app.queue.dispatcher import enqueue_lifecycle_job
from app.queue.models import JobStatus, ReviewJob
from app.services.github_service import github_service

logger = logging.getLogger(__name__)


# Raised when an action conflicts with another active review on the same PR
# (e.g. rerun attempted while a newer review for the same PR is still running).
class ReviewLifecycleConflict(Exception):
    pass


# ── Action matrix ────────────────────────────────────────────────
# Only these status-action combos are allowed. Active statuses
# (queued/pending/running) expose Cancel ONLY — rerun/retry/restart on an
# active review would permit duplicate executions for the same PR.
_ALLOWED_ACTIONS = {
    "rerun": ("completed",),
    "retry": ("failed", "timed_out"),
    "restart": ("stopped", "cancelled"),
    "cancel": ("queued", "pending", "running"),
}


class ReviewLifecycleService:
    """Manages review lifecycle actions."""

    async def _validate_and_get_pr_data(
        self, db: AsyncSession, review: Review, action: str
    ) -> tuple[PullRequest, Repository, Installation]:
        """Validate action against the matrix, fetch PR/repo/installation,
        check real-time PR state from GitHub, and return (pr, repo, installation).

        Raises ValueError on any validation failure.
        """
        # Action matrix check
        allowed_statuses = _ALLOWED_ACTIONS.get(action, ())
        if review.status not in allowed_statuses:
            raise ValueError(
                f"Cannot {action} a review with status '{review.status}'. "
                f"Allowed statuses: {'/'.join(allowed_statuses)}"
            )

        # Fetch PR
        pr_result = await db.execute(
            select(PullRequest).where(PullRequest.id == review.pr_id)
        )
        pr = pr_result.scalars().first()
        if not pr:
            raise ValueError("Pull request not found for this review.")

        # Per-PR active-review guard: never allow a second execution for a PR
        # that already has an active review. The caller holds the PR row lock,
        # so this check is race-safe against concurrent lifecycle actions.
        if action != "cancel":
            other_active = await db.execute(
                select(Review.id)
                .where(
                    Review.pr_id == review.pr_id,
                    Review.id != review.id,
                    Review.status.in_(["queued", "pending", "running"]),
                )
                .limit(1)
            )
            if other_active.scalars().first() is not None:
                raise ReviewLifecycleConflict(
                    f"Cannot {action} this review while another review for pull request "
                    f"#{pr.pr_number} is still in progress. Wait for it to finish first."
                )

        # Fetch repo
        repo_result = await db.execute(
            select(Repository).where(Repository.id == pr.repo_id)
        )
        repo = repo_result.scalars().first()
        if not repo:
            raise ValueError("Repository not found.")

        # Fetch installation
        inst_result = await db.execute(
            select(Installation).where(Installation.id == repo.installation_id)
        )
        installation = inst_result.scalars().first()
        if not installation:
            raise ValueError("GitHub App installation not found.")

        # Real-time PR state check from GitHub
        if action != "cancel":
            gh_pr = await github_service.get_pull_request(
                repo.full_name, pr.pr_number, installation.installation_id
            )
            gh_state = gh_pr.get("state", "unknown")
            if gh_state == "unknown":
                logger.warning(
                    f"GitHub PR state is unknown for {repo.full_name}#{pr.pr_number} "
                    f"(installation {installation.installation_id}) — allowing {action} anyway"
                )
            elif gh_state != "open":
                raise ValueError(
                    f"Cannot {action} review on a {gh_state} pull request. "
                    "Lifecycle actions are only allowed on open pull requests."
                )

        return pr, repo, installation

    async def cancel_review(
        self,
        db: AsyncSession,
        review_id: UUID,
        user_id: UUID,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        """Cancel a queued or running review."""
        review_result = await db.execute(select(Review).where(Review.id == review_id))
        review = review_result.scalars().first()
        if not review:
            raise ValueError("Review not found.")

        if review.status not in _ALLOWED_ACTIONS["cancel"]:
            return {
                "status": "success",
                "message": f"Review already in terminal state: {review.status}",
            }

        old_status = review.status
        await db.execute(
            __import__("sqlalchemy")
            .update(Review)
            .where(Review.id == review_id)
            .values(status="cancelled", error_message="Cancelled by user")
        )
        from app.services.review_execution_service import mark_execution_final

        await mark_execution_final(db, review_id, "cancelled")

        pr_result = await db.execute(
            select(PullRequest).where(PullRequest.id == review.pr_id)
        )
        pr = pr_result.scalars().first()

        if pr:
            # Cancel the job for THIS review.
            # Lifecycle jobs embed the review ID in delivery_id ("{action}-{review_id}").
            # Fall back to repo+PR match for webhook jobs (delivery GUID has no review link).
            job_cancel = await db.execute(
                __import__("sqlalchemy")
                .update(ReviewJob)
                .where(
                    ReviewJob.repo_id == pr.repo_id,
                    ReviewJob.pr_number == pr.pr_number,
                    ReviewJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
                    ReviewJob.delivery_id.like(f"%-{review_id}"),
                )
                .values(status=JobStatus.CANCELLED)
            )
            if job_cancel.rowcount == 0:
                await db.execute(
                    __import__("sqlalchemy")
                    .update(ReviewJob)
                    .where(
                        ReviewJob.repo_id == pr.repo_id,
                        ReviewJob.pr_number == pr.pr_number,
                        ReviewJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
                    )
                    .values(status=JobStatus.CANCELLED)
                )

            check_run_id = review.github_check_run_id
            if check_run_id:
                try:
                    repo_result = await db.execute(
                        select(Repository).where(Repository.id == pr.repo_id)
                    )
                    repo = repo_result.scalars().first()
                    if repo:
                        inst_result = await db.execute(
                            select(Installation).where(
                                Installation.id == repo.installation_id
                            )
                        )
                        installation = inst_result.scalars().first()
                        if installation:
                            from app.github.client import GitHubClient

                            owner, repo_name = repo.full_name.split("/", 1)
                            await GitHubClient().update_check_run(
                                installation_id=installation.installation_id,
                                owner=owner,
                                repo=repo_name,
                                check_run_id=check_run_id,
                                status="completed",
                                output={
                                    "title": "Revora Review Cancelled",
                                    "summary": "The review was cancelled by the user.",
                                    "conclusion": "cancelled",
                                },
                            )
                except Exception as e:
                    logger.warning(f"Failed to close GitHub check run on cancel: {e}")

        await db.commit()

        await self._audit(
            db,
            actor_id=str(user_id),
            action="review.cancelled",
            entity_type="review",
            entity_id=str(review_id),
            details={"old_status": old_status},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await db.commit()

        return {"status": "success", "message": "Review cancelled."}

    async def rerun_completed_review(
        self,
        db: AsyncSession,
        review_id: UUID,
        user_id: UUID,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        return await self._lifecycle_action(
            "rerun",
            db,
            review_id,
            user_id,
            ip_address,
            user_agent,
        )

    async def retry_failed_review(
        self,
        db: AsyncSession,
        review_id: UUID,
        user_id: UUID,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        return await self._lifecycle_action(
            "retry",
            db,
            review_id,
            user_id,
            ip_address,
            user_agent,
        )

    async def restart_stopped_review(
        self,
        db: AsyncSession,
        review_id: UUID,
        user_id: UUID,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        return await self._lifecycle_action(
            "restart",
            db,
            review_id,
            user_id,
            ip_address,
            user_agent,
        )

    async def _lifecycle_action(
        self,
        action: str,
        db: AsyncSession,
        review_id: UUID,
        user_id: UUID,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        """Shared implementation for rerun/retry/restart.

        Validates the action, checks real-time PR status, REUSES the existing
        review row (updates it in place), records a ReviewExecution, and
        enqueues a job. Never creates a new Review row.
        """
        review_result = await db.execute(select(Review).where(Review.id == review_id))
        review = review_result.scalars().first()
        if not review:
            raise ValueError("Review not found.")

        # Lock the PR row to serialize concurrent lifecycle actions for the same PR
        pr_lock = await db.execute(
            select(PullRequest).where(PullRequest.id == review.pr_id).with_for_update()
        )
        pr_lock.fetchone()

        pr, repo, installation = await self._validate_and_get_pr_data(
            db, review, action
        )

        settings = repo.settings or {}
        provider = settings.get("assigned_provider", "")
        model = settings.get("assigned_model", "")
        key_id = settings.get("assigned_key_id", "")

        # Reuse the SAME review row — never insert another one.
        review.status = "queued"
        review.started_at = None
        review.completed_at = None
        review.summary = None
        review.error_message = None
        db.add(review)
        await db.commit()
        await db.refresh(review)

        # Record this run as a new execution on the reused review row
        from app.services.review_execution_service import create_execution

        execution = await create_execution(
            db, review.id, trigger=action, commit_sha=pr.head_sha
        )
        await db.commit()

        payload = {
            "installation": {"id": installation.installation_id},
            "repository": {
                "owner": {"login": repo.full_name.split("/")[0]},
                "name": repo.name,
                "full_name": repo.full_name,
                "private": repo.is_private,
                "id": repo.github_id,
            },
            "pull_request": {
                "number": pr.pr_number,
                "title": pr.title,
                "body": "",
                "head": {"sha": pr.head_sha, "ref": pr.head_branch},
                "base": {"ref": pr.base_branch},
                "user": {"login": pr.author},
                "additions": pr.additions,
                "deletions": pr.deletions,
                "changed_files": pr.changed_files,
            },
            "_lifecycle": {
                "action": action,
                "original_review_id": str(review_id),
                "new_review_id": str(review.id),
                "execution_id": str(execution.id),
                "provider": provider,
                "model": model,
                "api_key_id": key_id,
            },
        }

        # Execution context (commit before enqueue so review+context are persisted)
        exec_ctx = ReviewExecutionContext(
            review_id=review.id,
            repository_full_name=repo.full_name,
            provider=provider,
            api_key_id=self._safe_uuid(key_id),
            model=model,
            commit_sha=pr.head_sha,
            base_branch=pr.base_branch,
            head_branch=pr.head_branch,
            pr_number=pr.pr_number,
            configuration_snapshot=settings,
        )
        db.add(exec_ctx)
        await db.commit()

        # Enqueue the background job (separate transaction).
        # delivery_id is unique per execution (the review row is reused across
        # reruns, so a review-based id would be deduped by the queue).
        delivery_id = f"{action}-{execution.id}"
        try:
            await enqueue_lifecycle_job(
                db,
                payload,
                delivery_id,
                repo_id=pr.repo_id,
                pr_number=pr.pr_number,
                head_sha=pr.head_sha,
            )
        except Exception as e:
            logger.error(
                f"Failed to enqueue lifecycle job for review {review.id}: {e}",
                exc_info=True,
            )
            await db.rollback()
            review.status = "failed"
            review.error_message = f"Failed to enqueue {action} job: {e}"
            db.add(review)
            await db.commit()

        await self._audit(
            db,
            actor_id=str(user_id),
            action=f"review.{action}",
            entity_type="review",
            entity_id=str(review.id),
            details={
                "review_id": str(review.id),
                "execution_id": str(execution.id),
                "action": action,
                "provider": provider,
                "model": model,
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await db.commit()

        return {
            "status": "success",
            "message": f"Review {action} initiated.",
            "new_review_id": str(review.id),
        }

    async def get_review_history(
        self,
        db: AsyncSession,
        pr_id: UUID,
        current_review_id: UUID,
    ) -> dict[str, Any]:
        """Return all review lifecycles for the PR plus the current review's executions.

        Reopened PRs create a new review row, so a PR can have several review
        rows — all of them remain visible here as history. Execution history
        (rerun/retry/restart/webhook runs) lives in review_executions.
        """
        from app.models.execution import ReviewExecution

        reviews_result = await db.execute(
            select(Review)
            .where(Review.pr_id == pr_id)
            .order_by(Review.created_at.desc())
        )
        reviews = reviews_result.scalars().all()

        lifecycles = []
        for r in reviews:
            lifecycles.append(
                {
                    "id": str(r.id),
                    "status": r.status,
                    "summary": r.summary,
                    "stats": r.stats or {},
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "completed_at": (
                        r.completed_at.isoformat() if r.completed_at else None
                    ),
                    "error_message": r.error_message,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "github_check_run_id": r.github_check_run_id,
                }
            )

        exec_result = await db.execute(
            select(ReviewExecution)
            .where(ReviewExecution.review_id == current_review_id)
            .order_by(ReviewExecution.execution_number.asc())
        )
        executions = []
        for e in exec_result.scalars().all():
            executions.append(
                {
                    "id": str(e.id),
                    "execution_number": e.execution_number,
                    "trigger": e.trigger,
                    "status": e.status,
                    "started_at": e.started_at.isoformat() if e.started_at else None,
                    "completed_at": (
                        e.completed_at.isoformat() if e.completed_at else None
                    ),
                    "duration_ms": e.duration_ms,
                    "model": e.model,
                    "provider": e.provider,
                    "tokens": e.tokens or {},
                }
            )

        return {
            "lifecycles": lifecycles,
            "executions": executions,
        }

    async def get_review_timeline(
        self,
        db: AsyncSession,
        review_id: UUID,
    ) -> list[dict[str, Any]]:
        from sqlalchemy import text

        stmt = text(
            """
            SELECT id, stage, status, started_at, completed_at, duration_ms, message, metrics
            FROM review_timelines
            WHERE review_id = :review_id
            ORDER BY COALESCE(started_at, created_at) ASC
        """
        )
        result = await db.execute(stmt, {"review_id": str(review_id)})
        rows = result.fetchall()

        return [
            {
                "id": str(r[0]),
                "stage": r[1],
                "status": r[2],
                "started_at": r[3].isoformat() if r[3] else None,
                "completed_at": r[4].isoformat() if r[4] else None,
                "duration_ms": r[5],
                "message": r[6],
                "metrics": r[7] or {},
            }
            for r in rows
        ]

    def _safe_uuid(self, value: str | None) -> UUID | None:
        if not value:
            return None
        try:
            return UUID(value)
        except ValueError:
            logger.warning(f"Invalid UUID value: {value}")
            return None

    async def _audit(
        self,
        db: AsyncSession,
        actor_id: str,
        action: str,
        entity_type: str,
        entity_id: str,
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ):
        log = AuditLog(
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(log)
        await db.flush()


review_lifecycle_service = ReviewLifecycleService()
