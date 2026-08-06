"""Tests for review lifecycle concurrency rules (C1/C2) and startup recovery."""

import uuid

import pytest

from app.cache.memory_cache import memory_cache
from app.models.github import Installation, PullRequest, Repository
from app.models.review import Review
from app.queue.models import JobStatus, ReviewJob
from app.services.github_service import github_service
from app.services.review_lifecycle import (
    _ALLOWED_ACTIONS,
    ReviewLifecycleConflict,
    review_lifecycle_service,
)


@pytest.mark.asyncio
async def test_action_matrix_restricts_rerun_to_completed():
    assert _ALLOWED_ACTIONS["rerun"] == ("completed",)
    assert set(_ALLOWED_ACTIONS["retry"]) == {"failed", "timed_out"}
    assert set(_ALLOWED_ACTIONS["restart"]) == {"stopped", "cancelled"}
    assert set(_ALLOWED_ACTIONS["cancel"]) == {"queued", "pending", "running"}


@pytest.mark.asyncio
async def test_rerun_rejected_while_review_active(test_db, mock_user):
    inst = Installation(
        installation_id=123456,
        account_id=999,
        account_login="test-org",
        account_type="Organization",
        user_id=mock_user.id,
        repository_selection="all",
        permissions={},
        events={},
    )
    test_db.add(inst)
    await test_db.flush()

    repo = Repository(
        github_id=555,
        name="repo",
        full_name="test-org/repo",
        is_private=True,
        installation_id=inst.id,
    )
    test_db.add(repo)
    await test_db.flush()

    pr = PullRequest(
        repo_id=repo.id,
        pr_number=1,
        title="Test PR",
        author="test-org",
        head_sha="a" * 40,
        base_branch="main",
        head_branch="feature",
        status="open",
    )
    test_db.add(pr)
    await test_db.flush()

    running = Review(pr_id=pr.id, status="running")
    test_db.add(running)
    await test_db.commit()
    await test_db.refresh(running)

    with pytest.raises(ValueError):
        await review_lifecycle_service._validate_and_get_pr_data(test_db, running, "rerun")


@pytest.mark.asyncio
async def test_pr_active_guard_blocks_rerun_when_other_review_active(
    test_db, mock_user, monkeypatch
):
    async def fake_get_pr(*args, **kwargs):
        return {"state": "open"}

    monkeypatch.setattr(github_service, "get_pull_request", fake_get_pr)

    inst = Installation(
        installation_id=223456,
        account_id=998,
        account_login="test-org",
        account_type="Organization",
        user_id=mock_user.id,
        repository_selection="all",
        permissions={},
        events={},
    )
    test_db.add(inst)
    await test_db.flush()

    repo = Repository(
        github_id=556,
        name="repo",
        full_name="test-org/repo",
        is_private=True,
        installation_id=inst.id,
    )
    test_db.add(repo)
    await test_db.flush()

    pr = PullRequest(
        repo_id=repo.id,
        pr_number=2,
        title="Test PR",
        author="test-org",
        head_sha="b" * 40,
        base_branch="main",
        head_branch="feature",
        status="open",
    )
    test_db.add(pr)
    await test_db.flush()

    active = Review(pr_id=pr.id, status="running")
    terminal = Review(pr_id=pr.id, status="completed")
    test_db.add_all([active, terminal])
    await test_db.commit()
    await test_db.refresh(active)
    await test_db.refresh(terminal)

    with pytest.raises(ReviewLifecycleConflict):
        await review_lifecycle_service._validate_and_get_pr_data(test_db, terminal, "rerun")


@pytest.mark.asyncio
async def test_pr_active_guard_allows_when_no_other_active(
    test_db, mock_user, monkeypatch
):
    async def fake_get_pr(*args, **kwargs):
        return {"state": "open"}

    monkeypatch.setattr(github_service, "get_pull_request", fake_get_pr)

    inst = Installation(
        installation_id=323456,
        account_id=997,
        account_login="test-org",
        account_type="Organization",
        user_id=mock_user.id,
        repository_selection="all",
        permissions={},
        events={},
    )
    test_db.add(inst)
    await test_db.flush()

    repo = Repository(
        github_id=557,
        name="repo",
        full_name="test-org/repo",
        is_private=True,
        installation_id=inst.id,
    )
    test_db.add(repo)
    await test_db.flush()

    pr = PullRequest(
        repo_id=repo.id,
        pr_number=3,
        title="Test PR",
        author="test-org",
        head_sha="c" * 40,
        base_branch="main",
        head_branch="feature",
        status="open",
    )
    test_db.add(pr)
    await test_db.flush()

    terminal = Review(pr_id=pr.id, status="completed")
    test_db.add(terminal)
    await test_db.commit()
    await test_db.refresh(terminal)

    pr, repo_out, inst_out = await review_lifecycle_service._validate_and_get_pr_data(
        test_db, terminal, "rerun"
    )
    assert pr.id == pr.id
    assert repo_out.id == repo.id
    assert inst_out.id == inst.id


@pytest.mark.asyncio
async def test_recover_stale_reviews_on_startup(test_db, mock_user, monkeypatch):
    from app.services import recovery

    inst = Installation(
        installation_id=423456,
        account_id=996,
        account_login="test-org",
        account_type="Organization",
        user_id=mock_user.id,
        repository_selection="all",
        permissions={},
        events={},
    )
    test_db.add(inst)
    await test_db.flush()

    repo = Repository(
        github_id=558,
        name="repo",
        full_name="test-org/repo",
        is_private=True,
        installation_id=inst.id,
    )
    test_db.add(repo)
    await test_db.flush()

    pr_stale = PullRequest(
        repo_id=repo.id,
        pr_number=4,
        title="Test PR",
        author="test-org",
        head_sha="d" * 40,
        base_branch="main",
        head_branch="feature",
        status="open",
    )
    pr_backed = PullRequest(
        repo_id=repo.id,
        pr_number=5,
        title="Test PR 2",
        author="test-org",
        head_sha="e" * 40,
        base_branch="main",
        head_branch="feature",
        status="open",
    )
    test_db.add_all([pr_stale, pr_backed])
    await test_db.flush()

    stale = Review(pr_id=pr_stale.id, status="running")
    test_db.add(stale)
    await test_db.flush()

    backed = Review(pr_id=pr_backed.id, status="running")
    test_db.add(backed)
    await test_db.flush()

    job = ReviewJob(
        delivery_id=f"webhook-{uuid.uuid4()}",
        head_sha="e" * 40,
        pr_number=5,
        repo_id=repo.id,
        payload={},
        status=JobStatus.QUEUED,
    )
    test_db.add(job)
    await test_db.commit()
    await test_db.refresh(stale)
    await test_db.refresh(backed)

    class _Ctx:
        def __init__(self, session):
            self._session = session

        async def __aenter__(self):
            return self._session

        async def __aexit__(self, *args):
            return False

    class _FakeSessionMaker:
        def __init__(self, session):
            self._session = session

        def __call__(self):
            return _Ctx(self._session)

    monkeypatch.setattr(recovery, "AsyncSessionLocal", _FakeSessionMaker(test_db))

    count = await recovery.recover_stale_reviews_on_startup()

    assert count == 1
    await test_db.refresh(stale)
    await test_db.refresh(backed)
    assert stale.status == "failed"
    assert "Server restarted" in stale.error_message
    assert backed.status == "running"


@pytest.mark.asyncio
async def test_invalidate_pr_cache():
    cache_key = "github:pr:test-org/repo:42"
    await memory_cache.set(cache_key, {"state": "closed"}, ttl_seconds=60)
    assert await memory_cache.get(cache_key) is not None

    await github_service.invalidate_pr_cache("test-org/repo", 42)
    assert await memory_cache.get(cache_key) is None
