"""Regression tests for the GitHub PR reopen lifecycle.

ONE Review card per logical PR: completed -> close -> reopen must REUSE the
existing Review row (reset to pending) and append a new ReviewExecution
(trigger="reopened") — never insert a second Review card.

Covers:
 1. New PR (opened) -> one Review
 2. Completed PR -> reopen -> same Review ID + new ReviewExecution
 3. Multiple reopens -> one Review + multiple executions
 4. Completed -> manual rerun -> same Review + new execution
 5. Cancelled -> restart -> same Review + new execution
 6. Duplicate webhook delivery -> no duplicate job/review/execution
 7. Synchronize (new commit) -> same Review + new execution
 8. Different PRs -> different Review cards
 9. Worker failure -> Failed state persists (review + execution)
10. Stale job recovery -> one bad job doesn't abort the recovery pass
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.execution import ReviewExecution
from app.models.github import Installation, PullRequest, Repository
from app.models.review import Review
from app.models.user import User
from app.queue.models import JobStatus, ReviewJob

SHA1 = "a" * 40
SHA2 = "b" * 40
FULL_NAME = "testowner/test-repo"
INSTALLATION_ID = 424242


def _repo_dict(github_id: int) -> dict:
    return {
        "id": github_id,
        "name": "test-repo",
        "full_name": FULL_NAME,
        "private": False,
    }


def _pr_dict(pr_number: int = 27, sha: str = SHA1) -> dict:
    return {
        "number": pr_number,
        "title": "Test PR",
        "body": "",
        "user": {"login": "author"},
        "head": {"sha": sha, "ref": "feat"},
        "base": {"ref": "main"},
        "additions": 5,
        "deletions": 3,
        "changed_files": 2,
    }


def _payload(pr_number: int = 27, sha: str = SHA1, repo_github_id: int = 777) -> dict:
    return {
        "installation": {"id": INSTALLATION_ID},
        "repository": {**_repo_dict(repo_github_id), "owner": {"login": "testowner"}},
        "pull_request": _pr_dict(pr_number, sha),
    }


@pytest.fixture
def session_factory(test_engine):
    """Patch every AsyncSessionLocal used along the webhook -> worker path."""
    factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    with (
        patch("app.github.shared.AsyncSessionLocal", factory),
        patch("app.queue.worker.AsyncSessionLocal", factory),
        patch("app.db.session.AsyncSessionLocal", factory),
        patch("app.services.recovery.AsyncSessionLocal", factory),
    ):
        yield factory


@pytest.fixture(autouse=True)
async def clean_tables(session_factory):
    yield
    async with session_factory() as db:
        for model in (
            ReviewExecution,
            Review,
            PullRequest,
            Repository,
            Installation,
            ReviewJob,
            User,
        ):
            await db.execute(model.__table__.delete())
        await db.commit()


async def _seed_user_installation(session_factory, repo_github_id: int = 777):
    """Seed user/installation/repo (no PR, no review) — returns dict."""
    async with session_factory() as db:
        user = User(
            id=uuid.uuid4(),
            name="Test User",
            email="test@example.com",
            role="user",
            is_verified=True,
        )
        db.add(user)
        installation = Installation(
            id=uuid.uuid4(),
            installation_id=INSTALLATION_ID,
            account_id=999,
            account_login="testowner",
            account_type="User",
            user_id=user.id,
            repository_selection="all",
            permissions={},
            events={},
        )
        db.add(installation)
        repo = Repository(
            id=uuid.uuid4(),
            github_id=repo_github_id,
            name="test-repo",
            full_name=FULL_NAME,
            is_private=False,
            installation_id=installation.id,
            reviews_enabled=True,
        )
        db.add(repo)
        await db.commit()
        return {"user": user, "installation": installation, "repo": repo}


async def _get_reviews(session_factory, pr_id):
    async with session_factory() as db:
        res = await db.execute(
            select(Review).where(Review.pr_id == pr_id).order_by(Review.created_at)
        )
        return res.scalars().all()


async def _get_executions(session_factory, review_id):
    async with session_factory() as db:
        res = await db.execute(
            select(ReviewExecution)
            .where(ReviewExecution.review_id == review_id)
            .order_by(ReviewExecution.execution_number)
        )
        return res.scalars().all()


async def _get_pr(session_factory, repo_id, pr_number):
    async with session_factory() as db:
        res = await db.execute(
            select(PullRequest).where(
                PullRequest.repo_id == repo_id,
                PullRequest.pr_number == pr_number,
            )
        )
        return res.scalars().first()


async def _complete_review(session_factory, review_id):
    """Simulate a finished pipeline run: job completed + review + execution."""
    from app.services.review_execution_service import mark_execution_final

    async with session_factory() as db:
        res = await db.execute(select(Review).where(Review.id == review_id))
        review = res.scalars().first()
        review.status = "completed"
        review.completed_at = datetime.now(UTC)
        db.add(review)
        await mark_execution_final(
            db, review_id, "completed", summary="done", stats={"ok": True}
        )
        # Settle the queue like the worker loop does after a run.
        pr_res = await db.execute(
            select(PullRequest).where(PullRequest.id == review.pr_id)
        )
        pr = pr_res.scalars().first()
        if pr is not None:
            job_res = await db.execute(
                select(ReviewJob).where(
                    ReviewJob.repo_id == pr.repo_id,
                    ReviewJob.pr_number == pr.pr_number,
                    ReviewJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
                )
            )
            for job in job_res.scalars().all():
                job.status = JobStatus.COMPLETED
                job.completed_at = datetime.now(UTC)
                db.add(job)
        await db.commit()


async def _enqueue(session_factory, action, delivery_id, pr_number=27, sha=SHA1):
    """Enqueue via the real dispatcher path (as webhooks.py does)."""
    from app.queue.dispatcher import enqueue_review_job

    async with session_factory() as db:
        job = await enqueue_review_job(
            db, _payload(pr_number, sha), delivery_id, webhook_action=action
        )
        return job


class TestReopenLifecycle:
    async def test_1_opened_creates_one_review(self, session_factory):
        await _seed_user_installation(session_factory)
        job = await _enqueue(session_factory, "opened", "delivery-1")
        assert job is not None

        async with session_factory() as db:
            repo_res = await db.execute(
                select(Repository).where(Repository.github_id == 777)
            )
            repo = repo_res.scalars().first()

        db_pr = await _get_pr(session_factory, repo.id, 27)
        assert db_pr is not None
        reviews = await _get_reviews(session_factory, db_pr.id)
        assert len(reviews) == 1
        assert reviews[0].status == "pending"
        execs = await _get_executions(session_factory, reviews[0].id)
        assert len(execs) == 1

    async def test_2_reopen_reuses_same_review(self, session_factory):
        await _seed_user_installation(session_factory)
        await _enqueue(session_factory, "opened", "delivery-1")

        async with session_factory() as db:
            repo = (
                await db.execute(select(Repository).where(Repository.github_id == 777))
            ).scalars().first()
        db_pr = await _get_pr(session_factory, repo.id, 27)
        original = (await _get_reviews(session_factory, db_pr.id))[0]
        await _complete_review(session_factory, original.id)

        # Close -> reopen (new delivery ID, same commit).
        reopen_job = await _enqueue(session_factory, "reopened", "delivery-2")
        assert reopen_job is not None

        reviews = await _get_reviews(session_factory, db_pr.id)
        assert len(reviews) == 1, "reopen must NOT create a second Review card"
        assert reviews[0].id == original.id, "Review ID must remain the same"
        assert reviews[0].status == "pending"

        execs = await _get_executions(session_factory, original.id)
        assert len(execs) == 2
        assert execs[0].status == "completed"
        assert execs[1].trigger == "reopened"
        assert execs[1].commit_sha == SHA1
        assert execs[1].status in ("queued", "pending")

    async def test_3_multiple_reopens_one_review_many_executions(
        self, session_factory
    ):
        await _seed_user_installation(session_factory)
        await _enqueue(session_factory, "opened", "delivery-1")

        async with session_factory() as db:
            repo = (
                await db.execute(select(Repository).where(Repository.github_id == 777))
            ).scalars().first()
        db_pr = await _get_pr(session_factory, repo.id, 27)
        original_id = (await _get_reviews(session_factory, db_pr.id))[0].id
        await _complete_review(session_factory, original_id)

        for i in range(2, 5):
            # Settle the previous reopen run before reopening again.
            reviews = await _get_reviews(session_factory, db_pr.id)
            await _complete_review(session_factory, reviews[0].id)
            job = await _enqueue(session_factory, "reopened", f"delivery-{i}")
            assert job is not None

        reviews = await _get_reviews(session_factory, db_pr.id)
        assert len(reviews) == 1
        assert reviews[0].id == original_id
        execs = await _get_executions(session_factory, original_id)
        # 1 (opened) + 3 (reopens)
        assert len(execs) == 4
        assert [e.execution_number for e in execs] == [1, 2, 3, 4]

    async def test_6_duplicate_delivery_no_duplicates(self, session_factory):
        await _seed_user_installation(session_factory)
        first = await _enqueue(session_factory, "opened", "delivery-dup")
        assert first is not None

        # Exact redelivery (same delivery_id + sha) -> deduped at the queue.
        dup = await _enqueue(session_factory, "opened", "delivery-dup")
        assert dup is None

        async with session_factory() as db:
            repo = (
                await db.execute(select(Repository).where(Repository.github_id == 777))
            ).scalars().first()
        db_pr = await _get_pr(session_factory, repo.id, 27)
        reviews = await _get_reviews(session_factory, db_pr.id)
        assert len(reviews) == 1
        execs = await _get_executions(session_factory, reviews[0].id)
        assert len(execs) == 1

    async def test_7_synchronize_reuses_same_review(self, session_factory):
        await _seed_user_installation(session_factory)
        await _enqueue(session_factory, "opened", "delivery-1")

        async with session_factory() as db:
            repo = (
                await db.execute(select(Repository).where(Repository.github_id == 777))
            ).scalars().first()
        db_pr = await _get_pr(session_factory, repo.id, 27)
        original_id = (await _get_reviews(session_factory, db_pr.id))[0].id
        await _complete_review(session_factory, original_id)

        # New commit pushed.
        job = await _enqueue(session_factory, "synchronize", "delivery-sync", sha=SHA2)
        assert job is not None

        reviews = await _get_reviews(session_factory, db_pr.id)
        assert len(reviews) == 1
        assert reviews[0].id == original_id
        execs = await _get_executions(session_factory, original_id)
        assert len(execs) == 2
        assert execs[1].trigger == "synchronize"
        assert execs[1].commit_sha == SHA2

    async def test_8_different_prs_different_cards(self, session_factory):
        await _seed_user_installation(session_factory)
        await _enqueue(session_factory, "opened", "delivery-pr27", pr_number=27)
        await _enqueue(session_factory, "opened", "delivery-pr28", pr_number=28)

        async with session_factory() as db:
            repo = (
                await db.execute(select(Repository).where(Repository.github_id == 777))
            ).scalars().first()
        pr27 = await _get_pr(session_factory, repo.id, 27)
        pr28 = await _get_pr(session_factory, repo.id, 28)
        r27 = await _get_reviews(session_factory, pr27.id)
        r28 = await _get_reviews(session_factory, pr28.id)
        assert len(r27) == 1 and len(r28) == 1
        assert r27[0].id != r28[0].id

    async def test_reopen_without_prior_review_creates_fallback(
        self, session_factory
    ):
        """Missed opened event: reopen with no Review row must still review."""
        await _seed_user_installation(session_factory)
        job = await _enqueue(session_factory, "reopened", "delivery-missed")
        assert job is not None

        async with session_factory() as db:
            repo = (
                await db.execute(select(Repository).where(Repository.github_id == 777))
            ).scalars().first()
        # PR row itself may not exist yet either (missed opened entirely).
        db_pr = await _get_pr(session_factory, repo.id, 27)
        assert db_pr is not None
        reviews = await _get_reviews(session_factory, db_pr.id)
        assert len(reviews) == 1

    async def test_reopen_while_active_does_not_duplicate(self, session_factory):
        """Reopen arriving mid-run supersedes but keeps ONE card."""
        await _seed_user_installation(session_factory)
        await _enqueue(session_factory, "opened", "delivery-1")

        async with session_factory() as db:
            repo = (
                await db.execute(select(Repository).where(Repository.github_id == 777))
            ).scalars().first()
        db_pr = await _get_pr(session_factory, repo.id, 27)
        original_id = (await _get_reviews(session_factory, db_pr.id))[0].id

        # Mark the first job running so the reopen races an active review.
        # (Same sha still queued -> job-level guard skips; force the review
        # active with a running job on another sha is unrealistic — instead
        # complete the queued job guard by using a fresh delivery on the
        # same sha after marking review running.)
        async with session_factory() as db:
            res = await db.execute(select(Review).where(Review.id == original_id))
            review = res.scalars().first()
            review.status = "running"
            db.add(review)
            await db.commit()

        # Same-sha reopen while a job is still queued for that sha -> skipped,
        # in-flight run covers the reopen. Still exactly one card.
        job = await _enqueue(session_factory, "reopened", "delivery-race")
        reviews = await _get_reviews(session_factory, db_pr.id)
        assert len(reviews) == 1
        assert reviews[0].id == original_id
        assert job is None  # covered by the in-flight run, not duplicated


class TestManualLifecycleActions:
    async def _setup_completed(self, session_factory):
        await _seed_user_installation(session_factory)
        await _enqueue(session_factory, "opened", "delivery-1")
        async with session_factory() as db:
            repo = (
                await db.execute(select(Repository).where(Repository.github_id == 777))
            ).scalars().first()
        db_pr = await _get_pr(session_factory, repo.id, 27)
        review_id = (await _get_reviews(session_factory, db_pr.id))[0].id
        await _complete_review(session_factory, review_id)
        return repo, db_pr, review_id

    async def test_4_rerun_reuses_same_review(self, session_factory, monkeypatch):
        from app.services.github_service import github_service
        from app.services.review_lifecycle import review_lifecycle_service

        async def fake_get_pr(*a, **k):
            return {"state": "open"}

        monkeypatch.setattr(github_service, "get_pull_request", fake_get_pr)
        repo, db_pr, review_id = await self._setup_completed(session_factory)

        async with session_factory() as db:
            user_res = await db.execute(select(User).limit(1))
            user = user_res.scalars().first()
            result = await review_lifecycle_service.rerun_completed_review(
                db, review_id, user.id
            )
        assert result["status"] == "success"
        assert result["new_review_id"] == str(review_id)

        reviews = await _get_reviews(session_factory, db_pr.id)
        assert len(reviews) == 1
        assert reviews[0].id == review_id
        assert reviews[0].status == "queued"
        execs = await _get_executions(session_factory, review_id)
        assert len(execs) == 2
        assert execs[1].trigger == "rerun"

    async def test_5_restart_cancelled_reuses_same_review(
        self, session_factory, monkeypatch
    ):
        from app.services.github_service import github_service
        from app.services.review_lifecycle import review_lifecycle_service

        async def fake_get_pr(*a, **k):
            return {"state": "open"}

        monkeypatch.setattr(github_service, "get_pull_request", fake_get_pr)
        await _seed_user_installation(session_factory)
        await _enqueue(session_factory, "opened", "delivery-1")
        async with session_factory() as db:
            repo = (
                await db.execute(select(Repository).where(Repository.github_id == 777))
            ).scalars().first()
        db_pr = await _get_pr(session_factory, repo.id, 27)
        review_id = (await _get_reviews(session_factory, db_pr.id))[0].id

        # Cancel the running review first.
        async with session_factory() as db:
            user = (await db.execute(select(User).limit(1))).scalars().first()
            cancel_res = await review_lifecycle_service.cancel_review(
                db, review_id, user.id
            )
            assert cancel_res["status"] == "success"

        async with session_factory() as db:
            res = await db.execute(select(Review).where(Review.id == review_id))
            assert res.scalars().first().status == "cancelled"

        # Restart reuses the same card.
        async with session_factory() as db:
            user = (await db.execute(select(User).limit(1))).scalars().first()
            result = await review_lifecycle_service.restart_stopped_review(
                db, review_id, user.id
            )
        assert result["status"] == "success"
        assert result["new_review_id"] == str(review_id)

        reviews = await _get_reviews(session_factory, db_pr.id)
        assert len(reviews) == 1
        assert reviews[0].id == review_id
        execs = await _get_executions(session_factory, review_id)
        triggers = [e.trigger for e in execs]
        assert "restart" in triggers


class TestWorkerFailureRecovery:
    async def test_9_worker_failure_persists_failed_state(self, session_factory):
        """_fail_job_and_review must persist review=failed + execution error."""
        from app.queue.worker import _fail_job_and_review

        seed = await _seed_user_installation(session_factory)
        repo = seed["repo"]
        async with session_factory() as db:
            pr = PullRequest(
                repo_id=repo.id,
                pr_number=27,
                title="Test PR",
                author="author",
                head_sha=SHA1,
                base_branch="main",
                head_branch="feat",
                status="open",
            )
            db.add(pr)
            await db.flush()
            review = Review(pr_id=pr.id, status="running")
            db.add(review)
            await db.flush()
            job = ReviewJob(
                delivery_id=f"rerun-{review.id}",
                head_sha=SHA1,
                pr_number=27,
                repo_id=repo.id,
                payload={},
                status=JobStatus.RUNNING,
            )
            db.add(job)
            await db.commit()
            review_id, job_id = review.id, job.id

        async with session_factory() as db:
            res = await db.execute(select(ReviewJob).where(ReviewJob.id == job_id))
            db_job = res.scalars().first()
            await _fail_job_and_review(db, db_job, "boom: pipeline exploded")
            await db.commit()

        async with session_factory() as db:
            res = await db.execute(select(Review).where(Review.id == review_id))
            assert res.scalars().first().status == "failed"
            exec_res = await db.execute(
                select(ReviewExecution).where(
                    ReviewExecution.review_id == review_id
                )
            )
            failed_execs = [e for e in exec_res.scalars().all() if e.status == "failed"]
            assert failed_execs, "execution must be marked failed with error detail"
            assert "boom" in (failed_execs[0].error_message or "")

    async def test_10_stale_recovery_isolates_bad_jobs(
        self, session_factory, monkeypatch
    ):
        """One bad job during recovery must not abort the whole pass."""
        import app.queue.worker as worker_mod

        seed = await _seed_user_installation(session_factory)
        repo = seed["repo"]
        async with session_factory() as db:
            pr = PullRequest(
                repo_id=repo.id,
                pr_number=27,
                title="Test PR",
                author="author",
                head_sha=SHA1,
                base_branch="main",
                head_branch="feat",
                status="open",
            )
            db.add(pr)
            await db.flush()
            for suffix in ("good", "bad"):
                review = Review(pr_id=pr.id, status="queued")
                db.add(review)
                await db.flush()
                db.add(
                    ReviewJob(
                        delivery_id=f"webhook-{suffix}-{uuid.uuid4()}",
                        head_sha=SHA1 if suffix == "good" else SHA2,
                        pr_number=27,
                        repo_id=repo.id,
                        payload={},
                        status=JobStatus.QUEUED,
                        created_at=datetime.now(UTC) - timedelta(minutes=60),
                    )
                )
            await db.commit()

        real_fail = worker_mod._fail_job_and_review
        calls: list[str] = []

        async def flaky_fail(session, job, message):
            calls.append(str(job.delivery_id))
            if "bad" in str(job.delivery_id):
                raise RuntimeError("simulated per-job failure")
            return await real_fail(session, job, message)

        monkeypatch.setattr(worker_mod, "_fail_job_and_review", flaky_fail)

        # recover_orphaned_jobs must not raise despite the bad job.
        await worker_mod.recover_orphaned_jobs(queue_timeout_minutes=30)

        assert len(calls) == 2, "both stale jobs must be attempted"
        async with session_factory() as db:
            res = await db.execute(
                select(func.count())
                .select_from(ReviewJob)
                .where(ReviewJob.status == JobStatus.FAILED)
            )
            assert res.scalar() == 1, "the good job must still be marked failed"
