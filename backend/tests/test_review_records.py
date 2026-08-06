"""Regression tests for the duplicate-review bug.

A user-cancelled review must never be resurrected by a stale queued job:
the worker's get_or_create_review_records call (find_existing_pending=True)
must not create a new Review row when the PR already has one for this
lifecycle, and process_job must bail out on cancelled jobs.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.execution import ReviewExecution
from app.models.github import Installation, PullRequest, Repository
from app.models.review import Review
from app.models.user import User
from app.queue.models import JobStatus, ReviewJob

SHA = "8ddf79c83ed93072212689717dfb332bba385071"
FULL_NAME = "testowner/test-repo"


def _repo_dict(github_id: int) -> dict:
    return {
        "id": github_id,
        "name": "test-repo",
        "full_name": FULL_NAME,
        "private": False,
    }


def _pr_dict(pr_number: int = 1, sha: str = SHA) -> dict:
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


def _payload(
    installation_id: int, repo_github_id: int, pr_number: int = 1, sha: str = SHA
) -> dict:
    return {
        "installation": {"id": installation_id},
        "repository": {**_repo_dict(repo_github_id), "owner": {"login": "testowner"}},
        "pull_request": _pr_dict(pr_number, sha),
    }


@pytest.fixture
def session_factory(test_engine):
    """Sessionmaker over the test engine, patching AsyncSessionLocal in the
    modules under test (they open their own sessions internally)."""
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


async def _seed(session_factory, review_status: str | None = None) -> dict:
    """Seed user/installation/repo/pr (and optionally one review row)."""
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
            installation_id=12345,
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
            github_id=777,
            name="test-repo",
            full_name=FULL_NAME,
            is_private=False,
            installation_id=installation.id,
            reviews_enabled=True,
        )
        db.add(repo)

        pr = PullRequest(
            id=uuid.uuid4(),
            repo_id=repo.id,
            pr_number=1,
            title="Test PR",
            author="author",
            head_sha=SHA,
            base_branch="main",
            head_branch="feat",
            status="open",
        )
        db.add(pr)

        review = None
        if review_status:
            review = Review(pr_id=pr.id, status=review_status)
            db.add(review)

        await db.commit()
        await db.refresh(repo)
        await db.refresh(pr)
        if review:
            await db.refresh(review)
        return {
            "user_id": str(user.id),
            "installation": installation,
            "repo": repo,
            "pr": pr,
            "review": review,
        }


async def _count_reviews(session_factory, pr_id) -> int:
    async with session_factory() as db:
        result = await db.execute(
            __import__("sqlalchemy").select(Review).where(Review.pr_id == pr_id)
        )
        return len(result.scalars().all())


class TestGetOrCreateReviewRecords:
    """The worker path must never create a second Review row per lifecycle."""

    async def test_fresh_pr_creates_review(self, session_factory):
        seed = await _seed(session_factory)

        from app.github.shared import get_or_create_review_records

        db_review, _, db_pr, _ = await get_or_create_review_records(
            12345,
            _repo_dict(seed["repo"].github_id),
            _pr_dict(),
            "webhook-1",
            status="running",
            find_existing_pending=True,
        )

        assert db_pr.id == seed["pr"].id
        assert db_review.status == "running"
        assert await _count_reviews(session_factory, seed["pr"].id) == 1

    async def test_pending_review_is_reused(self, session_factory):
        seed = await _seed(session_factory, review_status="pending")

        from app.github.shared import get_or_create_review_records

        db_review, _, _, _ = await get_or_create_review_records(
            12345,
            _repo_dict(seed["repo"].github_id),
            _pr_dict(),
            "webhook-1",
            status="running",
            find_existing_pending=True,
        )

        assert db_review.id == seed["review"].id
        assert db_review.status == "running"
        assert await _count_reviews(session_factory, seed["pr"].id) == 1

    async def test_cancelled_review_is_not_resurrected(self, session_factory):
        """Regression: a cancelled review must block new row creation."""
        seed = await _seed(session_factory, review_status="cancelled")

        from app.github.shared import get_or_create_review_records

        db_review, _, _, _ = await get_or_create_review_records(
            12345,
            _repo_dict(seed["repo"].github_id),
            _pr_dict(),
            "webhook-1",
            status="running",
            find_existing_pending=True,
        )

        assert db_review.id == seed["review"].id
        assert db_review.status == "cancelled"
        assert await _count_reviews(session_factory, seed["pr"].id) == 1

    async def test_find_existing_pending_false_still_creates_new_row(
        self, session_factory
    ):
        """Dispatcher path (opened/reopened) keeps creating fresh rows."""
        seed = await _seed(session_factory, review_status="completed")

        from app.github.shared import get_or_create_review_records

        db_review, _, _, _ = await get_or_create_review_records(
            12345,
            _repo_dict(seed["repo"].github_id),
            _pr_dict(),
            "webhook-1",
            status="pending",
            find_existing_pending=False,
        )

        assert db_review.id != seed["review"].id
        assert db_review.status == "pending"
        assert await _count_reviews(session_factory, seed["pr"].id) == 2


class TestWorkerStaleJobGuard:
    """process_job must not execute (or resurrect) stale/cancelled work."""

    async def test_cancelled_job_is_skipped(self, session_factory):
        from app.queue.worker import process_job

        seed = await _seed(session_factory)
        job_id = uuid.uuid4()
        async with session_factory() as db:
            db.add(
                ReviewJob(
                    id=job_id,
                    repo_id=seed["repo"].id,
                    pr_number=1,
                    head_sha=SHA,
                    delivery_id="193741d0-8d5e-11f1-82fe-0dd0b19f3e9f",
                    payload=_payload(12345, 777),
                    status=JobStatus.CANCELLED,
                )
            )
            await db.commit()

        with (
            patch(
                "app.github.auth.github_app_auth.get_installation_token",
                AsyncMock(return_value="tok"),
            ),
            patch("app.github.webhooks.get_pr_diff", AsyncMock(return_value="diff")),
            patch("app.pipeline.orchestrator.review_pipeline", MagicMock()),
        ):
            from app.pipeline.orchestrator import review_pipeline

            result = await process_job(
                (
                    job_id,
                    seed["repo"].id,
                    1,
                    SHA,
                    "193741d0-8d5e-11f1-82fe-0dd0b19f3e9f",
                    _payload(12345, 777),
                    0,
                    datetime.now(UTC),
                )
            )
            review_pipeline.execute.assert_not_called()

        assert result is False
        assert await _count_reviews(session_factory, seed["pr"].id) == 0

    async def test_terminal_review_is_skipped(self, session_factory):
        from app.queue.worker import process_job

        seed = await _seed(session_factory, review_status="cancelled")
        job_id = uuid.uuid4()
        async with session_factory() as db:
            db.add(
                ReviewJob(
                    id=job_id,
                    repo_id=seed["repo"].id,
                    pr_number=1,
                    head_sha=SHA,
                    delivery_id="193741d0-8d5e-11f1-82fe-0dd0b19f3e9f",
                    payload=_payload(12345, 777),
                    status=JobStatus.RUNNING,
                )
            )
            await db.commit()

        with (
            patch(
                "app.github.auth.github_app_auth.get_installation_token",
                AsyncMock(return_value="tok"),
            ),
            patch("app.github.webhooks.get_pr_diff", AsyncMock(return_value="diff")),
            patch("app.pipeline.orchestrator.review_pipeline", MagicMock()),
        ):
            from app.pipeline.orchestrator import review_pipeline

            result = await process_job(
                (
                    job_id,
                    seed["repo"].id,
                    1,
                    SHA,
                    "193741d0-8d5e-11f1-82fe-0dd0b19f3e9f",
                    _payload(12345, 777),
                    0,
                    datetime.now(UTC),
                )
            )
            review_pipeline.execute.assert_not_called()

        assert result is False
        assert await _count_reviews(session_factory, seed["pr"].id) == 1
