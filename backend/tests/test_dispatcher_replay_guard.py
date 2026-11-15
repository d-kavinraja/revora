"""N6 — a redelivered webhook for an already-completed commit enqueues nothing."""
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.models.execution import ReviewExecution
from app.models.github import Installation, PullRequest, Repository
from app.models.review import Review
from app.models.user import User
from app.queue.dispatcher import enqueue_review_job
from app.queue.models import ReviewJob

SHA = "e" * 40


def _payload(pr_number: int = 55, sha: str = SHA) -> dict:
    return {
        "action": "opened",
        "installation": {"id": 606060, "app_id": 12345},
        "repository": {
            "id": 707070,
            "name": "replay-repo",
            "full_name": "replay-owner/replay-repo",
            "private": False,
            "owner": {"login": "replay-owner"},
        },
        "pull_request": {
            "number": pr_number,
            "title": "Replay guard",
            "body": "",
            "user": {"login": "author"},
            "head": {"sha": sha, "ref": "feat"},
            "base": {"ref": "main"},
        },
    }


async def _seed_completed_review(session) -> Review:
    user = User(
        id=uuid.uuid4(),
        name="Replay User",
        email="replay@example.com",
        role="user",
        is_verified=True,
    )
    session.add(user)
    await session.flush()

    installation = Installation(
        id=uuid.uuid4(),
        installation_id=606060,
        account_id=6060,
        account_login="replay-owner",
        account_type="User",
        user_id=user.id,
        repository_selection="all",
        permissions={"contents": "read"},
        events={},
        permissions_ok=True,
        app_id=12345,
    )
    session.add(installation)
    await session.flush()

    repo = Repository(
        id=uuid.uuid4(),
        github_id=707070,
        name="replay-repo",
        full_name="replay-owner/replay-repo",
        installation_id=installation.id,
        reviews_enabled=True,
    )
    session.add(repo)
    await session.flush()

    pr = PullRequest(
        id=uuid.uuid4(),
        repo_id=repo.id,
        pr_number=55,
        title="Replay guard",
        author="author",
        head_sha=SHA,
        base_branch="main",
        head_branch="feat",
        status="open",
    )
    session.add(pr)
    await session.flush()

    review = Review(id=uuid.uuid4(), pr_id=pr.id, status="completed")
    session.add(review)
    await session.flush()

    execution = ReviewExecution(
        id=uuid.uuid4(),
        review_id=review.id,
        execution_number=1,
        trigger="opened",
        status="completed",
        commit_sha=SHA,
        completed_at=datetime.now(UTC),
    )
    session.add(execution)
    await session.commit()
    return review


async def test_completed_commit_redelivery_enqueues_nothing(test_db):
    await _seed_completed_review(test_db)

    job = await enqueue_review_job(
        test_db, _payload(), f"delivery-{uuid.uuid4()}", webhook_action="opened"
    )

    assert job is None
    result = await test_db.execute(select(ReviewJob))
    assert result.scalars().all() == []


async def test_completed_commit_synchronize_redelivery_enqueues_nothing(test_db):
    await _seed_completed_review(test_db)

    # Align the seeded execution with a synchronize trigger.
    from sqlalchemy import update

    review = (
        await test_db.execute(select(Review))
    ).scalars().one()
    await test_db.execute(
        update(ReviewExecution)
        .where(ReviewExecution.review_id == review.id)
        .values(trigger="synchronize")
    )

    job = await enqueue_review_job(
        test_db,
        _payload(),
        f"delivery-{uuid.uuid4()}",
        webhook_action="synchronize",
    )

    assert job is None


async def test_reopened_is_not_blocked_by_completed_opened_execution(
    test_db, monkeypatch
):
    from unittest.mock import AsyncMock

    await _seed_completed_review(test_db)
    monkeypatch.setattr(
        "app.queue.dispatcher._reuse_latest_review_for_pr", AsyncMock()
    )

    job = await enqueue_review_job(
        test_db,
        _payload(),
        f"delivery-{uuid.uuid4()}",
        webhook_action="reopened",
    )

    assert job is not None
    assert job.head_sha == SHA
