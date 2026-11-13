"""Regression: the `reviews` page flag gates only user-facing access.

Disabling the Reviews page must never stop the background review lifecycle:
GitHub webhook -> dispatcher -> queue -> worker claim -> execution ->
persistence. Re-enabling the flag must expose the accumulated history again.
"""

import hashlib
import hmac
import json
import uuid
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.auth import SESSION_COOKIE_NAME, create_access_token
from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.middleware.rate_limit import limiter
from app.models.execution import ReviewExecution
from app.models.github import Installation, PullRequest, Repository
from app.models.platform import FeatureFlag, PlatformSetting
from app.models.review import Review
from app.models.user import User
from app.queue.models import JobStatus, ReviewJob
from app.queue.worker import claim_next_job_with_factory, process_job
from app.services.platform_settings import platform_settings_service
from app.services.review_execution_service import mark_execution_final
from app.services.review_selection import ResolvedSelection

SHA = "c" * 40
INSTALLATION_ID = 515151
REPO_GITHUB_ID = 818181
FULL_NAME = "testowner/feature-gate-repo"


def _payload(pr_number: int = 41, sha: str = SHA) -> dict:
    return {
        "action": "opened",
        "installation": {"id": INSTALLATION_ID},
        "repository": {
            "id": REPO_GITHUB_ID,
            "name": "feature-gate-repo",
            "full_name": FULL_NAME,
            "private": False,
            "owner": {"login": "testowner"},
        },
        "pull_request": {
            "number": pr_number,
            "title": "Feature gate regression",
            "body": "",
            "user": {"login": "author"},
            "head": {"sha": sha, "ref": "feat"},
            "base": {"ref": "main"},
            "additions": 5,
            "deletions": 3,
            "changed_files": 2,
        },
    }


def _headers(body: bytes, delivery_id: str) -> dict[str, str]:
    signature = (
        "sha256="
        + hmac.new(
            settings.GITHUB_WEBHOOK_SECRET.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
    )
    return {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": signature,
        "Content-Type": "application/json",
    }


def _post_webhook(payload: dict, delivery_id: str) -> TestClient:
    body = json.dumps(payload).encode()
    with TestClient(app) as client:
        return client.post(
            "/api/v1/webhooks/github",
            content=body,
            headers=_headers(body, delivery_id),
        )


@pytest.fixture(autouse=True)
def _reset_limiter():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
async def reviews_env(test_engine):
    """Committed-session factory patched into every session user on the path."""
    factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    with ExitStack() as stack:
        for target in (
            "app.github.webhooks.AsyncSessionLocal",
            "app.github.shared.AsyncSessionLocal",
            "app.queue.worker.AsyncSessionLocal",
            "app.db.session.AsyncSessionLocal",
        ):
            stack.enter_context(patch(target, factory))
        yield factory

    async with factory() as db:
        for model in (
            ReviewExecution,
            Review,
            PullRequest,
            Repository,
            Installation,
            ReviewJob,
            User,
            FeatureFlag,
            PlatformSetting,
        ):
            await db.execute(model.__table__.delete())
        await db.commit()


async def _seed(factory) -> dict:
    async with factory() as db:
        user = User(
            id=uuid.uuid4(),
            name="Gate User",
            email="gate@example.com",
            role="user",
            is_verified=True,
        )
        db.add(user)
        await db.flush()

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
            permissions_ok=True,
        )
        db.add(installation)
        await db.flush()

        repo = Repository(
            id=uuid.uuid4(),
            github_id=REPO_GITHUB_ID,
            name="feature-gate-repo",
            full_name=FULL_NAME,
            is_private=False,
            installation_id=installation.id,
            reviews_enabled=True,
        )
        db.add(repo)
        await db.commit()
        return {"user_id": user.id, "repo_id": repo.id}


async def _set_flag(factory, key: str, status: str) -> None:
    async with factory() as db:
        await platform_settings_service.set_flag(db, key, status=status)
        await db.commit()
    platform_settings_service.clear_cache()


async def _single_job(factory) -> ReviewJob:
    async with factory() as db:
        result = await db.execute(select(ReviewJob))
        return result.scalars().one()


async def _single_review(factory) -> Review:
    async with factory() as db:
        result = await db.execute(select(Review))
        return result.scalars().one()


async def _latest_execution(factory) -> ReviewExecution:
    async with factory() as db:
        result = await db.execute(
            select(ReviewExecution).order_by(ReviewExecution.execution_number.desc())
        )
        return result.scalars().first()


@contextmanager
def _user_client(factory, user_id: uuid.UUID) -> Iterator[TestClient]:
    async def override_get_db():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            client.cookies.set(
                SESSION_COOKIE_NAME,
                create_access_token(subject=str(user_id)),
            )
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_reviews_flag_disabled_gates_access_but_not_background_processing(
    reviews_env, monkeypatch
):
    seed = await _seed(reviews_env)
    await _set_flag(reviews_env, "reviews", "disabled")

    resolved = ResolvedSelection(
        provider="openai",
        provider_slug="openai",
        provider_name="OpenAI",
        model="gpt-4o-mini",
        api_key_id=None,
        source="user_routing",
        repository_mapping_status="unmapped",
        repository_provider=None,
        repository_model=None,
    )
    monkeypatch.setattr(
        "app.services.review_selection.resolve_selection",
        AsyncMock(return_value=resolved),
    )
    monkeypatch.setattr(
        "app.services.provider_registry.provider_registry_service.ensure_usable",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.github.auth.github_app_auth.get_installation_token",
        AsyncMock(return_value="installation-token"),
    )
    monkeypatch.setattr(
        "app.github.webhooks.get_pr_diff",
        AsyncMock(return_value="diff --git a/file.py b/file.py"),
    )
    monkeypatch.setattr(
        "app.services.github_service.github_service.get_pull_request",
        AsyncMock(return_value={"state": "open"}),
    )

    async def fake_execute(**kwargs) -> dict:
        async with reviews_env() as db:
            await db.execute(
                update(Review)
                .where(Review.id == kwargs["review_id"])
                .values(status="completed", completed_at=datetime.now(UTC))
            )
            await mark_execution_final(
                db,
                kwargs["review_id"],
                "completed",
                summary="background review completed",
                stats={"issues": 0},
            )
            await db.commit()
        return {"status": "success"}

    monkeypatch.setattr(
        "app.pipeline.orchestrator.review_pipeline.execute", fake_execute
    )

    # 3. Signature verification still rejects a bad signature.
    body = json.dumps(_payload()).encode()
    with TestClient(app) as client:
        invalid = client.post(
            "/api/v1/webhooks/github",
            content=body,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": f"delivery-{uuid.uuid4()}",
                "X-Hub-Signature-256": "sha256=invalid",
                "Content-Type": "application/json",
            },
        )
    assert invalid.status_code == 401

    # 2-4. A valid signed webhook is accepted and still creates the job.
    response = _post_webhook(_payload(), f"delivery-{uuid.uuid4()}")
    assert response.status_code == 202, response.text

    job = await _single_job(reviews_env)
    review = await _single_review(reviews_env)
    execution = await _latest_execution(reviews_env)
    assert job.status == JobStatus.QUEUED
    assert review.status == "pending"
    assert execution is not None and execution.status == "queued"

    # 5. The worker can still claim the job.
    claimed = await claim_next_job_with_factory(reviews_env)
    assert claimed is not None
    assert claimed[0] == job.id

    async with reviews_env() as db:
        claimed_job = await db.get(ReviewJob, job.id)
        assert claimed_job.status == JobStatus.RUNNING

    # SQLite returns raw text() payloads as JSON strings; the worker receives a
    # decoded dict from Postgres. Normalize the test row before processing.
    claimed = list(claimed)
    if isinstance(claimed[5], str):
        claimed[5] = json.loads(claimed[5])

    # 6-7. Execution proceeds and review/execution records persist.
    assert await process_job(tuple(claimed)) is True

    async with reviews_env() as db:
        completed_review = await db.get(Review, review.id)
        completed_execution = await db.get(ReviewExecution, execution.id)
    assert completed_review.status == "completed"
    assert completed_execution.status == "completed"
    assert completed_execution.summary == "background review completed"

    # 8. Ordinary users still cannot use the disabled Reviews read APIs.
    with _user_client(reviews_env, seed["user_id"]) as client:
        listing = client.get("/api/v1/reviews")
        assert listing.status_code == 503
        assert listing.json()["code"] == "feature_disabled"

        detail = client.get(f"/api/v1/reviews/{review.id}")
        assert detail.status_code == 503
        assert detail.json()["code"] == "feature_disabled"

    # 9-10. Re-enabling restores access to the accumulated history.
    await _set_flag(reviews_env, "reviews", "enabled")

    with _user_client(reviews_env, seed["user_id"]) as client:
        listing = client.get("/api/v1/reviews")
        assert listing.status_code == 200, listing.text
        rows = listing.json()
        assert [row["id"] for row in rows] == [str(review.id)]
        assert rows[0]["status"] == "completed"

        detail = client.get(f"/api/v1/reviews/{review.id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["summary"] == "background review completed"


async def test_review_initiation_disabled_does_not_block_webhook_reviews(
    reviews_env,
):
    await _seed(reviews_env)
    await _set_flag(reviews_env, "review_initiation", "disabled")

    response = _post_webhook(_payload(pr_number=42), f"delivery-{uuid.uuid4()}")
    assert response.status_code == 202, response.text

    job = await _single_job(reviews_env)
    review = await _single_review(reviews_env)
    assert job.status == JobStatus.QUEUED
    assert review.status == "pending"
