"""Regression tests: multi-repository sync independence and truthful sync state.

Covers the P0 fixes:
  - Per-repo advisory locks (no shared global lock for single-repo syncs).
  - No fake SUCCESS on lock contention (FAILED with an honest error).
  - QUEUED sync state + duplicate-sync guard covering QUEUED and RUNNING.
  - Login reconciliation scoped to repos with local open PRs.
  - sync_state exposes prs_found/jobs_enqueued (zero-PR vs never-synced).
  - Worker scheduling: per-repo FIFO + cross-repo fairness (query shape).
"""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from app.models.github import Installation, PullRequest, Repository
from app.models.sync_run import (
    SYNC_STATUS_FAILED,
    SYNC_STATUS_QUEUED,
    SYNC_STATUS_RUNNING,
    SYNC_STATUS_SUCCESS,
    SyncRun,
)
from app.services import sync_engine
from app.services.sync_engine import record_sync_run


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _gh_pr(number, sha, title="Test PR"):
    return {
        "number": number,
        "title": title,
        "state": "open",
        "merged": False,
        "draft": False,
        "body": "body",
        "user": {"login": "test-org"},
        "head": {"sha": sha, "ref": "feature"},
        "base": {"ref": "main"},
        "additions": 10,
        "deletions": 2,
        "changed_files": 1,
    }


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data
        self.text = json.dumps(json_data or {})
        self.is_success = 200 <= status_code < 300

    def json(self):
        return self._json


class _FakeClient:
    """Fake httpx.AsyncClient routed by URL suffix."""

    def __init__(self, routes):
        self.routes = routes

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, *args, **kwargs):
        for suffix, response in self.routes.items():
            if url.endswith(suffix):
                return response() if callable(response) else response
        return _FakeResponse(404, {})


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


class _LockContendedSession:
    """Session wrapper whose advisory-lock attempt always fails."""

    def __init__(self, session):
        self._s = session

    async def scalar(self, *args, **kwargs):
        return False  # lock unavailable

    async def execute(self, *args, **kwargs):
        return await self._s.execute(*args, **kwargs)

    def add(self, *args, **kwargs):
        return self._s.add(*args, **kwargs)

    async def commit(self):
        return await self._s.commit()

    async def flush(self):
        return await self._s.flush()

    async def refresh(self, *args, **kwargs):
        return await self._s.refresh(*args, **kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _ContendedMaker:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return _LockContendedSession(self._session)


class _FakeBackgroundTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, func, *args, **kwargs):
        self.tasks.append((func, args, kwargs))


async def _install_repo(
    test_db,
    mock_user,
    *,
    gid,
    full_name,
    install_id,
):
    inst = Installation(
        installation_id=install_id,
        account_id=999,
        account_login="test-org",
        account_type="Organization",
        user_id=mock_user.id,
        repository_selection="all",
        permissions={
            "pull_requests": "write",
            "checks": "write",
            "contents": "read",
        },
        events={},
        permissions_ok=True,
    )
    test_db.add(inst)
    await test_db.flush()
    repo = Repository(
        github_id=gid,
        name=full_name.split("/")[1],
        full_name=full_name,
        is_private=False,
        installation_id=inst.id,
        reviews_enabled=True,
    )
    test_db.add(repo)
    await test_db.commit()
    await test_db.refresh(repo)
    return inst, repo


def _patch_sync(monkeypatch, test_db, client_fake=None):
    monkeypatch.setattr(sync_engine, "AsyncSessionLocal", _FakeSessionMaker(test_db))
    monkeypatch.setattr(
        sync_engine.github_app_auth,
        "get_installation_token",
        AsyncMock(return_value="tok"),
    )
    if client_fake is not None:
        monkeypatch.setattr(
            sync_engine.httpx, "AsyncClient", lambda *a, **k: client_fake
        )
    enqueue = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
    monkeypatch.setattr("app.queue.dispatcher.enqueue_review_job", enqueue)
    return enqueue


# ---------------------------------------------------------------------------
# Lock model
# ---------------------------------------------------------------------------


def test_full_pass_lock_separated_from_per_repo_lock():
    """The global lock must not be shared with single-repo syncs."""
    assert hasattr(sync_engine, "FULL_PASS_ADVISORY_LOCK_KEY")
    assert not hasattr(sync_engine, "SYNC_ADVISORY_LOCK_KEY")
    assert not hasattr(sync_engine, "_SYNC_ADVISORY_LOCK_KEY")

    repos_path = (
        Path(__file__).parent.parent
        / "app"
        / "api"
        / "v1"
        / "endpoints"
        / "repositories.py"
    )
    source = repos_path.read_text()
    assert "SYNC_ADVISORY_LOCK_KEY" not in source
    # Per-repo sync uses a per-repository advisory lock derived from repo_id.
    assert "hashtext(" in source


def test_worker_query_preserves_per_repo_fifo_with_fairness():
    """Worker must order FIFO within a repo and round-robin across repos.

    The claim is two-step so at most one repo lock is ever held:
    step 1 orders candidate repos WITHOUT taking locks, step 2 locks only
    the repo actually claimed. A separate global NOT EXISTS(running) gate
    enforces review concurrency = 1 across all repositories.
    """
    worker_path = (
        Path(__file__).parent.parent / "app" / "queue" / "worker.py"
    )
    source = worker_path.read_text()
    # Step 1: fair repo ordering, no advisory lock inside.
    assert "GROUP BY j.repo_id" in source
    assert "ORDER BY last_completed ASC" in source
    assert "MIN(j.created_at) AS oldest" in source
    # Step 2: per-repo oldest job with both the advisory lock and row lock.
    assert "pg_try_advisory_xact_lock(hashtext(j.repo_id::text))" in source
    assert "ORDER BY j.created_at ASC" in source
    assert "FOR UPDATE SKIP LOCKED" in source
    # Null-repo jobs (no per-repo gate) are still claimable.
    assert "j.repo_id IS NULL" in source
    # Global single-flight: one RUNNING job across all repositories.
    assert "WHERE gr.status = 'running'" in source
    assert "REVIEW_CLAIM_ADVISORY_LOCK_KEY" in source

    dispatcher_path = (
        Path(__file__).parent.parent / "app" / "queue" / "dispatcher.py"
    )
    dispatcher_source = dispatcher_path.read_text()
    # Inspection helper: same fairness ordering, but takes NO locks.
    assert "PARTITION BY j.repo_id ORDER BY j.created_at ASC" in dispatcher_source
    assert "pg_try_advisory_xact_lock" not in dispatcher_source


# ---------------------------------------------------------------------------
# Sync state machine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lock_contention_finalizes_failed_not_success(
    test_db, mock_user, monkeypatch
):
    """A repo that cannot acquire its per-repo lock must be FAILED, never SUCCESS."""
    import app.api.v1.endpoints.repositories as repos_module

    _, repo = await _install_repo(
        test_db, mock_user, gid=9001, full_name="test-org/locked", install_id=9101
    )
    run = await record_sync_run(
        test_db,
        "manual",
        SYNC_STATUS_RUNNING,
        triggered_by=mock_user.id,
        details={"repo_id": str(repo.id), "full_name": repo.full_name},
    )

    monkeypatch.setattr(
        "app.db.session.AsyncSessionLocal", _ContendedMaker(test_db)
    )

    result = await repos_module._background_single_repo_sync(
        repo.id, run.id, mock_user.id
    )
    assert result["prs_found"] == 0

    await test_db.refresh(run)
    assert run.status == SYNC_STATUS_FAILED
    assert run.error is not None and "lock" in run.error.lower()
    assert run.completed_at is not None


@pytest.mark.asyncio
async def test_queued_sync_blocks_duplicate_request(test_db, mock_user, monkeypatch):
    """A QUEUED run owns the repo: a second Sync request returns in_progress."""
    import app.api.v1.endpoints.repositories as repos_module

    _, repo = await _install_repo(
        test_db, mock_user, gid=9002, full_name="test-org/queued", install_id=9102
    )
    queued = await record_sync_run(
        test_db,
        "webhook",
        SYNC_STATUS_QUEUED,
        triggered_by=mock_user.id,
        details={"repo_id": str(repo.id), "full_name": repo.full_name},
    )

    active = await repos_module._find_active_repo_sync(test_db, repo.id)
    assert active is not None
    assert active.id == queued.id

    # The endpoint duplicate-sync guard must also fire for QUEUED runs.
    monkeypatch.setattr(
        repos_module.github_app_auth,
        "get_installation_token",
        AsyncMock(return_value="tok"),
    )
    tasks = _FakeBackgroundTasks()
    response = await repos_module.sync_repository(
        str(repo.id), tasks, test_db, mock_user
    )
    assert response["status"] == "in_progress"
    assert tasks.tasks == []


@pytest.mark.asyncio
async def test_sync_state_exposes_counts_for_zero_pr_distinction(
    test_db, mock_user
):
    """list_repositories must expose prs_found so 0-PRs != never-synced."""
    import app.api.v1.endpoints.repositories as repos_module

    _, repo = await _install_repo(
        test_db, mock_user, gid=9003, full_name="test-org/empty", install_id=9103
    )
    await record_sync_run(
        test_db,
        "manual",
        SYNC_STATUS_SUCCESS,
        counts={"repo_count": 1, "prs_found": 0, "jobs_enqueued": 0},
        triggered_by=mock_user.id,
        details={"repo_id": str(repo.id), "full_name": repo.full_name},
    )

    repos = await repos_module.list_repositories(test_db, mock_user)
    entry = next(r for r in repos if r["id"] == str(repo.id))
    assert entry["sync_state"] is not None
    assert entry["sync_state"]["status"] == "success"
    assert entry["sync_state"]["prs_found"] == 0
    assert entry["sync_state"]["jobs_enqueued"] == 0


# ---------------------------------------------------------------------------
# Multi-repo independence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_repos_sync_independently(test_db, mock_user, monkeypatch):
    """Repo A syncing must not prevent Repo B from syncing (no global skip)."""
    import app.api.v1.endpoints.repositories as repos_module

    _, repo_a = await _install_repo(
        test_db, mock_user, gid=9011, full_name="test-org/repo-a", install_id=9111
    )
    _, repo_b = await _install_repo(
        test_db, mock_user, gid=9012, full_name="test-org/repo-b", install_id=9112
    )

    sha_a = "a" * 40
    sha_b = "b" * 40
    client = _FakeClient(
        {
            "/repos/test-org/repo-a/pulls": _FakeResponse(200, [_gh_pr(1, sha_a)]),
            "/repos/test-org/repo-a/pulls/1": _FakeResponse(200, _gh_pr(1, sha_a)),
            "/repos/test-org/repo-b/pulls": _FakeResponse(200, [_gh_pr(10, sha_b)]),
            "/repos/test-org/repo-b/pulls/10": _FakeResponse(200, _gh_pr(10, sha_b)),
        }
    )
    _patch_sync(monkeypatch, test_db, client_fake=client)
    monkeypatch.setattr(
        "app.db.session.AsyncSessionLocal", _FakeSessionMaker(test_db)
    )
    monkeypatch.setattr(
        repos_module.github_app_auth,
        "get_installation_token",
        AsyncMock(return_value="tok"),
    )

    run_a = await record_sync_run(
        test_db,
        "manual",
        SYNC_STATUS_RUNNING,
        triggered_by=mock_user.id,
        details={"repo_id": str(repo_a.id), "full_name": repo_a.full_name},
    )
    run_b = await record_sync_run(
        test_db,
        "manual",
        SYNC_STATUS_RUNNING,
        triggered_by=mock_user.id,
        details={"repo_id": str(repo_b.id), "full_name": repo_b.full_name},
    )

    counts_a = await repos_module._background_single_repo_sync(
        repo_a.id, run_a.id, mock_user.id
    )
    counts_b = await repos_module._background_single_repo_sync(
        repo_b.id, run_b.id, mock_user.id
    )

    assert counts_a["prs_found"] == 1
    assert counts_a["jobs_enqueued"] == 1
    assert counts_b["prs_found"] == 1
    assert counts_b["jobs_enqueued"] == 1

    await test_db.refresh(run_a)
    await test_db.refresh(run_b)
    assert run_a.status == SYNC_STATUS_SUCCESS
    assert run_b.status == SYNC_STATUS_SUCCESS

    await test_db.refresh(repo_a)
    await test_db.refresh(repo_b)
    assert repo_a.last_synced_at is not None
    assert repo_b.last_synced_at is not None


@pytest.mark.asyncio
async def test_zero_pr_repo_records_success_with_zero_counts(
    test_db, mock_user, monkeypatch
):
    """A repo with no open PRs records SUCCESS with prs_found=0 (not 'never')."""
    import app.api.v1.endpoints.repositories as repos_module

    _, repo = await _install_repo(
        test_db, mock_user, gid=9021, full_name="test-org/quiet", install_id=9121
    )
    client = _FakeClient(
        {"/repos/test-org/quiet/pulls": _FakeResponse(200, [])}
    )
    _patch_sync(monkeypatch, test_db, client_fake=client)
    monkeypatch.setattr(
        "app.db.session.AsyncSessionLocal", _FakeSessionMaker(test_db)
    )
    monkeypatch.setattr(
        repos_module.github_app_auth,
        "get_installation_token",
        AsyncMock(return_value="tok"),
    )

    run = await record_sync_run(
        test_db,
        "manual",
        SYNC_STATUS_RUNNING,
        triggered_by=mock_user.id,
        details={"repo_id": str(repo.id), "full_name": repo.full_name},
    )
    counts = await repos_module._background_single_repo_sync(
        repo.id, run.id, mock_user.id
    )

    assert counts["prs_found"] == 0
    assert counts["jobs_enqueued"] == 0
    await test_db.refresh(run)
    assert run.status == SYNC_STATUS_SUCCESS
    await test_db.refresh(repo)
    assert repo.last_synced_at is not None


# ---------------------------------------------------------------------------
# Login reconciliation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_reconciliation_only_touches_repos_with_open_prs(
    test_db, mock_user, monkeypatch
):
    """Login must queue syncs for repos with local open PRs — nothing else."""
    _, repo_idle = await _install_repo(
        test_db, mock_user, gid=9031, full_name="test-org/idle", install_id=9131
    )
    _, repo_active = await _install_repo(
        test_db, mock_user, gid=9032, full_name="test-org/active", install_id=9132
    )
    pr = PullRequest(
        repo_id=repo_active.id,
        pr_number=7,
        title="Work",
        author="test-org",
        head_sha="d" * 40,
        base_branch="main",
        head_branch="feature",
        status="open",
    )
    test_db.add(pr)
    await test_db.commit()

    monkeypatch.setattr(
        "app.db.session.AsyncSessionLocal", _FakeSessionMaker(test_db)
    )
    monkeypatch.setattr(
        sync_engine, "sync_repositories_once", AsyncMock(return_value={})
    )
    process_mock = AsyncMock()
    monkeypatch.setattr(
        "app.api.v1.endpoints.repositories._process_queued_sync", process_mock
    )

    await sync_engine._login_reconciliation(mock_user.id)

    queued = (
        (
            await test_db.execute(
                select(SyncRun).where(
                    SyncRun.reason == "login",
                    SyncRun.status == SYNC_STATUS_QUEUED,
                )
            )
        )
        .scalars()
        .all()
    )
    repo_ids = {r.details["repo_id"] for r in queued}
    assert str(repo_active.id) in repo_ids
    assert str(repo_idle.id) not in repo_ids
    assert process_mock.await_count == len(queued)
