"""Selection snapshots for review executions (repository mapping vs routing)."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.api_key import ApiKey
from app.models.execution import ReviewExecution
from app.models.github import Installation, PullRequest, Repository
from app.models.provider import ProviderRegistry
from app.models.review import Review
from app.models.user import User
from app.queue.models import JobStatus, ReviewJob
from app.services.review_execution_service import (
    get_latest_execution,
    mark_execution_final,
)
from app.services.review_selection import selection_api_fields

SHA1 = "a" * 40
SHA2 = "b" * 40
INSTALLATION_ID = 515151


def _repo_dict(github_id: int) -> dict:
    return {
        "id": github_id,
        "name": "test-repo",
        "full_name": "testowner/test-repo",
        "private": False,
        "owner": {"login": "testowner"},
    }


def _payload(pr_number: int, sha: str = SHA1, github_id: int = 888) -> dict:
    return {
        "installation": {"id": INSTALLATION_ID},
        "repository": _repo_dict(github_id),
        "pull_request": {
            "number": pr_number,
            "title": f"Test PR {pr_number}",
            "body": "",
            "user": {"login": "author"},
            "head": {"sha": sha, "ref": "feat"},
            "base": {"ref": "main"},
            "additions": 1,
            "deletions": 1,
            "changed_files": 1,
        },
    }


@pytest.fixture
def session_factory(test_engine):
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
            ApiKey,
            ProviderRegistry,
            User,
        ):
            await db.execute(model.__table__.delete())
        await db.commit()


async def _seed(session_factory, *, settings=None, routing=None):
    async with session_factory() as db:
        user = User(
            id=uuid.uuid4(),
            name="Test User",
            email="selection@example.com",
            role="user",
            is_verified=True,
            settings={"model_routing": routing} if routing else {},
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
            github_id=888,
            name="test-repo",
            full_name="testowner/test-repo",
            is_private=False,
            installation_id=installation.id,
            reviews_enabled=True,
            settings=settings or {},
        )
        db.add(repo)
        await db.commit()
        await db.refresh(repo)
        return user, installation, repo


async def _seed_provider(db, name="gemini", model="gemma-4-26b-a4b-it"):
    provider = ProviderRegistry(
        name=name,
        display_name=name.title(),
        slug=name,
        litellm_provider=name,
        default_model=model,
        api_key_min_length=1,
        is_enabled=True,
        status="available",
    )
    db.add(provider)
    await db.commit()


async def _seed_key(db, user_id, provider="gemini"):
    key = ApiKey(
        user_id=user_id,
        provider=provider,
        encrypted_key="not-used",
        label="test",
        is_valid=True,
        is_enabled=True,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return key


async def _add_pr(db, repo, pr_number=1, sha=SHA1):
    pr = PullRequest(
        repo_id=repo.id,
        pr_number=pr_number,
        title=f"PR {pr_number}",
        author="author",
        head_sha=sha,
        base_branch="main",
        head_branch="feat",
        status="open",
        additions=1,
        deletions=1,
        changed_files=1,
    )
    db.add(pr)
    await db.commit()
    await db.refresh(pr)
    return pr


async def _enqueue(session_factory, pr_number, sha=SHA1, action="opened"):
    from app.queue.dispatcher import enqueue_review_job

    async with session_factory() as db:
        return await enqueue_review_job(
            db,
            _payload(pr_number, sha),
            f"delivery-{pr_number}-{sha[:4]}-{action}",
            webhook_action=action,
        )


async def _latest(session_factory, review_id):
    async with session_factory() as db:
        return await get_latest_execution(db, review_id)


async def _review_for_pr(session_factory, repo_id, pr_number):
    async with session_factory() as db:
        pr = (
            await db.execute(
                select(PullRequest).where(
                    PullRequest.repo_id == repo_id,
                    PullRequest.pr_number == pr_number,
                )
            )
        ).scalars().first()
        return (
            await db.execute(
                select(Review)
                .where(Review.pr_id == pr.id)
                .order_by(Review.created_at.desc())
            )
        ).scalars().first()


class TestSelectionSnapshots:
    async def test_mapped_second_pr_reuse_path_has_selection(self, session_factory):
        user, _installation, repo = await _seed(
            session_factory,
            settings={
                "assigned_provider": "gemini",
                "assigned_model": "gemma-4-26b-a4b-it",
            },
        )
        async with session_factory() as db:
            await _seed_provider(db)
            key = await _seed_key(db, user.id)
            repo = await db.merge(repo)
            repo.settings = {
                **repo.settings,
                "assigned_key_id": str(key.id),
            }
            db.add(repo)
            await db.commit()
            await _add_pr(db, repo, pr_number=3)

        await _enqueue(session_factory, 3)
        review = await _review_for_pr(session_factory, repo.id, 3)
        execution = await _latest(session_factory, review.id)
        assert execution is not None
        assert execution.provider == "gemini"
        assert execution.model == "gemma-4-26b-a4b-it"
        fields = selection_api_fields(execution)
        assert fields["repository_mapping_status"] == "mapped"
        assert fields["selection_source"] == "repository_mapping"
        assert fields["selected_provider"] == "gemini"
        assert fields["selected_model"] == "gemma-4-26b-a4b-it"
        assert fields["actual_execution_provider"] is None

    async def test_new_pr_path_and_second_pr_are_independent(self, session_factory):
        user, _installation, repo = await _seed(
            session_factory,
            settings={
                "assigned_provider": "gemini",
                "assigned_model": "gemma-4-26b-a4b-it",
            },
        )
        async with session_factory() as db:
            await _seed_provider(db)
            key = await _seed_key(db, user.id)
            repo = await db.merge(repo)
            repo.settings = {**repo.settings, "assigned_key_id": str(key.id)}
            db.add(repo)
            await db.commit()

        # PR #2 has no PullRequest row -> full creation path.
        await _enqueue(session_factory, 2)
        # PR #3 gets a pre-existing PR row -> reuse path.
        async with session_factory() as db:
            repo = await db.merge(repo)
            await _add_pr(db, repo, pr_number=3, sha=SHA2[0:40])
        await _enqueue(session_factory, 3, sha=SHA2)

        r2 = await _review_for_pr(session_factory, repo.id, 2)
        r3 = await _review_for_pr(session_factory, repo.id, 3)
        e2 = await _latest(session_factory, r2.id)
        e3 = await _latest(session_factory, r3.id)
        assert e2.provider == e3.provider == "gemini"
        assert e2.model == e3.model == "gemma-4-26b-a4b-it"
        assert e2.id != e3.id

    async def test_unmapped_repo_uses_routing_fallback(self, session_factory):
        user, _installation, repo = await _seed(
            session_factory,
            routing={
                "code_review": {
                    "provider": "openrouter",
                    "model": "cohere/north-mini-code:free",
                }
            },
        )
        async with session_factory() as db:
            await _seed_provider(db, "openrouter", "cohere/north-mini-code:free")
            await _seed_key(db, user.id, "openrouter")
            repo = await db.merge(repo)
            await _add_pr(db, repo, pr_number=4)

        await _enqueue(session_factory, 4)
        review = await _review_for_pr(session_factory, repo.id, 4)
        execution = await _latest(session_factory, review.id)
        fields = selection_api_fields(execution)
        assert fields["repository_mapping_status"] == "not_mapped"
        assert fields["selection_source"] == "routing_fallback"
        assert fields["selected_provider"] == "openrouter"
        assert fields["selected_model"] == "cohere/north-mini-code:free"

    async def test_unresolved_repo_records_no_selection(self, session_factory):
        _user, _installation, repo = await _seed(session_factory)
        async with session_factory() as db:
            await _add_pr(db, repo, pr_number=5)

        await _enqueue(session_factory, 5)
        review = await _review_for_pr(session_factory, repo.id, 5)
        execution = await _latest(session_factory, review.id)
        fields = selection_api_fields(execution)
        assert fields["repository_mapping_status"] == "not_mapped"
        assert fields["selection_source"] == "unresolved"
        assert fields["selected_provider"] is None
        assert fields["selected_model"] is None

    async def test_reopen_creates_new_snapshot_without_touching_previous(
        self, session_factory
    ):
        user, _installation, repo = await _seed(
            session_factory,
            settings={
                "assigned_provider": "gemini",
                "assigned_model": "gemma-4-26b-a4b-it",
            },
        )
        async with session_factory() as db:
            await _seed_provider(db)
            key = await _seed_key(db, user.id)
            repo = await db.merge(repo)
            repo.settings = {**repo.settings, "assigned_key_id": str(key.id)}
            db.add(repo)
            await db.commit()
            await _add_pr(db, repo, pr_number=6)

        await _enqueue(session_factory, 6)
        review = await _review_for_pr(session_factory, repo.id, 6)
        first = await _latest(session_factory, review.id)
        async with session_factory() as db:
            first = await db.merge(first)
            await mark_execution_final(db, review.id, "completed")
            jobs = (
                await db.execute(select(ReviewJob))
            ).scalars().all()
            for job in jobs:
                job.status = JobStatus.COMPLETED
                job.completed_at = datetime.now(UTC)
                db.add(job)
            await db.commit()

        await _enqueue(session_factory, 6, action="reopened")
        async with session_factory() as db:
            execs = (
                await db.execute(
                    select(ReviewExecution)
                    .where(ReviewExecution.review_id == review.id)
                    .order_by(ReviewExecution.execution_number)
                )
            ).scalars().all()
        assert len(execs) == 2
        assert execs[0].status == "completed"
        assert execs[1].trigger == "reopened"
        assert selection_api_fields(execs[1])["selected_provider"] == "gemini"
        assert selection_api_fields(execs[1])["selected_model"] == "gemma-4-26b-a4b-it"

    async def test_cancel_before_inference_preserves_selection(self, session_factory):
        user, _installation, repo = await _seed(
            session_factory,
            settings={
                "assigned_provider": "gemini",
                "assigned_model": "gemma-4-26b-a4b-it",
            },
        )
        async with session_factory() as db:
            await _seed_provider(db)
            key = await _seed_key(db, user.id)
            repo = await db.merge(repo)
            repo.settings = {**repo.settings, "assigned_key_id": str(key.id)}
            db.add(repo)
            await db.commit()
            await _add_pr(db, repo, pr_number=7)

        await _enqueue(session_factory, 7)
        review = await _review_for_pr(session_factory, repo.id, 7)
        async with session_factory() as db:
            await mark_execution_final(
                db, review.id, "cancelled", error_message="Cancelled by user"
            )
            await db.commit()
        execution = await _latest(session_factory, review.id)
        fields = selection_api_fields(execution)
        assert fields["selected_provider"] == "gemini"
        assert fields["selected_model"] == "gemma-4-26b-a4b-it"
        assert fields["actual_execution_provider"] is None
        assert fields["execution_started"] is False

    async def test_api_list_and_detail_expose_selection_contract(
        self, client, test_db, mock_user
    ):
        installation = Installation(
            id=uuid.uuid4(),
            installation_id=616161,
            account_id=999,
            account_login="testowner",
            account_type="User",
            user_id=mock_user.id,
            repository_selection="all",
            permissions={},
            events={},
        )
        test_db.add(installation)
        await test_db.flush()
        repo = Repository(
            id=uuid.uuid4(),
            github_id=999,
            name="test-repo",
            full_name="testowner/test-repo",
            is_private=False,
            installation_id=installation.id,
            reviews_enabled=True,
            settings={},
        )
        test_db.add(repo)
        await test_db.flush()
        pr = PullRequest(
            repo_id=repo.id,
            pr_number=11,
            title="API PR",
            author="author",
            head_sha=SHA1,
            base_branch="main",
            head_branch="feat",
            status="open",
        )
        test_db.add(pr)
        await test_db.flush()
        review = Review(pr_id=pr.id, status="queued")
        test_db.add(review)
        await test_db.commit()
        await test_db.refresh(review)
        execution = ReviewExecution(
            review_id=review.id,
            execution_number=1,
            trigger="webhook",
            status="queued",
            commit_sha=SHA1,
            provider="openrouter",
            model="cohere/north-mini-code:free",
            configuration_snapshot={
                "selection": {
                    "repository_mapping_status": "not_mapped",
                    "repository_provider": None,
                    "repository_model": None,
                    "selection_source": "user_routing",
                    "selected_provider": "openrouter",
                    "selected_provider_slug": "openrouter",
                    "selected_provider_name": "OpenRouter",
                    "selected_model": "cohere/north-mini-code:free",
                    "resolved_at": datetime.now(UTC).isoformat(),
                }
            },
        )
        test_db.add(execution)
        await test_db.commit()

        listed = client.get("/api/v1/reviews").json()
        item = next(r for r in listed if r["id"] == str(review.id))
        assert item["repository_mapping_status"] == "not_mapped"
        assert item["selection_source"] == "routing_fallback"
        assert item["selected_provider"] == "openrouter"
        assert item["selected_model"] == "cohere/north-mini-code:free"
        assert item["actual_execution_provider"] is None

        detail = client.get(f"/api/v1/reviews/{review.id}").json()
        assert detail["selected_provider"] == "openrouter"
        assert detail["current_execution"]["selected_model"] == (
            "cohere/north-mini-code:free"
        )
        assert "source" not in detail  # never leak raw snapshot


    async def test_retry_and_restart_snapshot_selection(self, session_factory):
        user, _installation, repo = await _seed(
            session_factory,
            settings={
                "assigned_provider": "gemini",
                "assigned_model": "gemma-4-26b-a4b-it",
            },
        )
        async with session_factory() as db:
            await _seed_provider(db)
            key = await _seed_key(db, user.id)
            repo = await db.merge(repo)
            repo.settings = {**repo.settings, "assigned_key_id": str(key.id)}
            db.add(repo)
            await db.commit()

        from app.services.review_lifecycle import review_lifecycle_service

        cases = [
            ("retry_failed_review", "failed", 21),
            ("restart_stopped_review", "stopped", 22),
        ]
        for method_name, review_status, pr_number in cases:
            async with session_factory() as db:
                pr = await _add_pr(db, repo, pr_number=pr_number)
                review = Review(pr_id=pr.id, status=review_status)
                db.add(review)
                await db.commit()
                await db.refresh(review)
                review_id = review.id

            async with session_factory() as db:
                with patch(
                    "app.services.review_lifecycle.github_service.get_pull_request",
                    AsyncMock(return_value={"state": "open"}),
                ):
                    await getattr(review_lifecycle_service, method_name)(
                        db, review_id, user.id
                    )

            execution = await _latest(session_factory, review_id)
            fields = selection_api_fields(execution)
            assert fields["selected_provider"] == "gemini"
            assert fields["selected_model"] == "gemma-4-26b-a4b-it"

    async def test_lifecycle_rerun_uses_routing_for_unmapped_repo(
        self, session_factory
    ):
        user, _installation, repo = await _seed(
            session_factory,
            routing={
                "code_review": {
                    "provider": "openrouter",
                    "model": "cohere/north-mini-code:free",
                }
            },
        )
        async with session_factory() as db:
            await _seed_provider(db, "openrouter", "cohere/north-mini-code:free")
            await _seed_key(db, user.id, "openrouter")
            pr = await _add_pr(db, repo, pr_number=8)
            review = Review(pr_id=pr.id, status="completed")
            db.add(review)
            await db.commit()
            await db.refresh(review)
            review_id = review.id

        from app.services.review_lifecycle import review_lifecycle_service

        async with session_factory() as db:
            with patch(
                "app.services.review_lifecycle.github_service.get_pull_request",
                AsyncMock(return_value={"state": "open"}),
            ):
                await review_lifecycle_service.rerun_completed_review(
                    db, review_id, user.id
                )
        execution = await _latest(session_factory, review_id)
        fields = selection_api_fields(execution)
        assert fields["selection_source"] == "routing_fallback"
        assert fields["selected_provider"] == "openrouter"
        assert fields["selected_model"] == "cohere/north-mini-code:free"
