"""Tests for the sync engine (automatic recovery & repository synchronization).

Covers: repository discovery (new/updated/removed-not-deleted/re-add),
reviews_enabled preservation, permission gating, PR reconciliation
(new → opened, head change → synchronize, same sha → noop), the
already-reviewed-commit guard, closed-PR reconcile, per-repo failure
isolation, tiered due computation, and sync_runs audit recording.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from app.services import sync_engine
from app.models.github import Installation, Repository, PullRequest
from app.models.review import Review
from app.models.execution import ReviewExecution
from app.models.sync_run import SyncRun


def _gh_pr(number, sha, state="open", title="Test PR", merged=False):
    return {
        "number": number,
        "title": title,
        "state": state,
        "merged": merged,
        "draft": False,
        "body": "body",
        "user": {"login": "test-org"},
        "head": {"sha": sha, "ref": "feature"},
        "base": {"ref": "main"},
        "additions": 10,
        "deletions": 2,
        "changed_files": 1,
    }


def _gh_repo(gid, full_name, archived=False, private=True):
    name = full_name.split("/")[1]
    return {
        "id": gid,
        "name": name,
        "full_name": full_name,
        "description": None,
        "language": "Python",
        "private": private,
        "archived": archived,
    }


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=None):
        self.status_code = status_code
        self._json = json_data
        self.text = text if text is not None else (json.dumps(json_data or {}) if json_data else "")
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
        return _FakeResponse(404, {}, "")

    async def delete(self, url, *args, **kwargs):
        return _FakeResponse(204, {}, "")

    async def post(self, url, *args, **kwargs):
        return _FakeResponse(201, {}, "")


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


async def _install_repo(test_db, mock_user, *, gid=1001, full_name="test-org/repo-a",
                       reviews_enabled=True, removed_at=None, permissions_ok=True,
                       last_synced_at=None, archived=False, install_id=None):
    if install_id is None:
        install_id = 8000 + gid
    inst = Installation(
        installation_id=install_id,
        account_id=999,
        account_login="test-org",
        account_type="Organization",
        user_id=mock_user.id,
        repository_selection="all",
        permissions={"pull_requests": "write", "checks": "write", "contents": "read", "issues": "write"},
        events={},
        permissions_ok=permissions_ok,
    )
    test_db.add(inst)
    await test_db.flush()
    repo = Repository(
        github_id=gid,
        name=full_name.split("/")[1],
        full_name=full_name,
        is_private=True,
        installation_id=inst.id,
        reviews_enabled=reviews_enabled,
        removed_at=removed_at,
        last_synced_at=last_synced_at,
        is_archived=archived,
    )
    test_db.add(repo)
    await test_db.commit()
    await test_db.refresh(repo)
    return inst, repo


async def _add_pr(test_db, repo, number, sha, status="open"):
    pr = PullRequest(
        repo_id=repo.id,
        pr_number=number,
        title="Test PR",
        author="test-org",
        head_sha=sha,
        base_branch="main",
        head_branch="feature",
        status=status,
    )
    test_db.add(pr)
    await test_db.commit()
    await test_db.refresh(pr)
    return pr


def _patch_sync_engine(monkeypatch, test_db, client_fake=None, enqueue_mock=None, token="tok"):
    monkeypatch.setattr(sync_engine, "AsyncSessionLocal", _FakeSessionMaker(test_db))
    monkeypatch.setattr(
        sync_engine.github_app_auth,
        "get_installation_token",
        AsyncMock(return_value=token),
    )
    monkeypatch.setattr(
        sync_engine.github_app_auth,
        "get_installation",
        AsyncMock(return_value={
            "id": 9001,
            "permissions": {"pull_requests": "write", "checks": "write", "contents": "read", "issues": "write"},
            "suspended_at": None,
        }),
    )
    if client_fake is not None:
        monkeypatch.setattr(sync_engine.httpx, "AsyncClient", lambda *a, **k: client_fake)
    if enqueue_mock is not None:
        monkeypatch.setattr("app.queue.dispatcher.enqueue_review_job", enqueue_mock)


# ---------------------------------------------------------------------------
# Repository pass
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_repo_pass_discovers_new_repo(test_db, mock_user, monkeypatch):
    await _install_repo(test_db, mock_user, gid=999, full_name="test-org/placeholder")
    client = _FakeClient({
        "/installation/repositories": _FakeResponse(200, {"repositories": [_gh_repo(777, "test-org/new-repo")]}),
    })
    _patch_sync_engine(monkeypatch, test_db, client_fake=client)

    counts = await sync_engine.sync_repositories_once("startup", user_id=mock_user.id)

    assert counts["repos_added"] == 1
    repo = (await test_db.execute(
        select(Repository).where(Repository.github_id == 777)
    )).scalars().first()
    assert repo is not None
    assert repo.full_name == "test-org/new-repo"
    assert repo.reviews_enabled is True
    assert repo.last_synced_at is not None
    # Placeholder repo vanished from GitHub → marked removed, not deleted.
    assert counts["repos_removed"] == 1


@pytest.mark.asyncio
async def test_repo_pass_marks_removed_not_deleted(test_db, mock_user, monkeypatch):
    inst, repo = await _install_repo(test_db, mock_user, gid=1001, full_name="test-org/repo-a")
    pr = await _add_pr(test_db, repo, 1, "a" * 40)
    review = Review(pr_id=pr.id, status="completed", summary="history")
    test_db.add(review)
    await test_db.commit()
    review_id = review.id

    # GitHub no longer lists repo-a (only repo-b).
    client = _FakeClient({
        "/installation/repositories": _FakeResponse(200, {"repositories": [_gh_repo(778, "test-org/repo-b")]}),
    })
    _patch_sync_engine(monkeypatch, test_db, client_fake=client)

    counts = await sync_engine.sync_repositories_once("startup", user_id=mock_user.id)

    assert counts["repos_removed"] == 1
    await test_db.refresh(repo)
    assert repo.removed_at is not None
    assert repo.reviews_enabled is False
    # History preserved: PR + review rows still exist.
    prs = (await test_db.execute(select(PullRequest).where(PullRequest.repo_id == repo.id))).scalars().all()
    assert len(prs) == 1
    reviews = (await test_db.execute(select(Review).where(Review.id == review_id))).scalars().all()
    assert len(reviews) == 1


@pytest.mark.asyncio
async def test_repo_pass_preserves_reviews_enabled(test_db, mock_user, monkeypatch):
    inst, repo = await _install_repo(test_db, mock_user, gid=1001, full_name="test-org/repo-a",
                                     reviews_enabled=False)
    client = _FakeClient({
        "/installation/repositories": _FakeResponse(200, {"repositories": [_gh_repo(1001, "test-org/repo-a")]}),
    })
    _patch_sync_engine(monkeypatch, test_db, client_fake=client)

    await sync_engine.sync_repositories_once("startup", user_id=mock_user.id)

    await test_db.refresh(repo)
    # User intent preserved — sync never force-re-enables a disabled repo.
    assert repo.reviews_enabled is False


@pytest.mark.asyncio
async def test_repo_pass_readds_previously_removed(test_db, mock_user, monkeypatch):
    inst, repo = await _install_repo(
        test_db, mock_user, gid=1001, full_name="test-org/repo-a",
        removed_at=datetime.now(timezone.utc), reviews_enabled=False,
    )
    client = _FakeClient({
        "/installation/repositories": _FakeResponse(200, {"repositories": [_gh_repo(1001, "test-org/repo-a")]}),
    })
    _patch_sync_engine(monkeypatch, test_db, client_fake=client)

    await sync_engine.sync_repositories_once("startup", user_id=mock_user.id)

    await test_db.refresh(repo)
    assert repo.removed_at is None
    assert repo.reviews_enabled is True


@pytest.mark.asyncio
async def test_repo_pass_updates_archived_flag(test_db, mock_user, monkeypatch):
    inst, repo = await _install_repo(test_db, mock_user, gid=1001, full_name="test-org/repo-a")
    client = _FakeClient({
        "/installation/repositories": _FakeResponse(200, {"repositories": [_gh_repo(1001, "test-org/repo-a", archived=True)]}),
    })
    _patch_sync_engine(monkeypatch, test_db, client_fake=client)

    await sync_engine.sync_repositories_once("startup", user_id=mock_user.id)

    await test_db.refresh(repo)
    assert repo.is_archived is True


# ---------------------------------------------------------------------------
# PR pass — discovery and guards
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pr_pass_new_pr_enqueues_opened(test_db, mock_user, monkeypatch):
    inst, repo = await _install_repo(test_db, mock_user, gid=1001, full_name="test-org/repo-a")
    sha = "b" * 40
    client = _FakeClient({
        "/repos/test-org/repo-a/pulls": _FakeResponse(200, [_gh_pr(7, sha)]),
        "/repos/test-org/repo-a/pulls/7": _FakeResponse(200, _gh_pr(7, sha)),
    })
    enqueue = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
    _patch_sync_engine(monkeypatch, test_db, client_fake=client, enqueue_mock=enqueue)

    counts = await sync_engine.sync_prs_once("startup")

    assert counts["prs_found"] == 1
    assert counts["jobs_enqueued"] == 1
    action = enqueue.call_args.kwargs["webhook_action"]
    delivery = enqueue.call_args.args[2]
    assert action == "opened"
    assert delivery == f"sync:1001:7:{sha}"


@pytest.mark.asyncio
async def test_pr_pass_head_change_enqueues_synchronize(test_db, mock_user, monkeypatch):
    inst, repo = await _install_repo(test_db, mock_user, gid=1001, full_name="test-org/repo-a")
    old_sha = "c" * 40
    new_sha = "d" * 40
    await _add_pr(test_db, repo, 8, old_sha)
    client = _FakeClient({
        "/repos/test-org/repo-a/pulls": _FakeResponse(200, [_gh_pr(8, new_sha)]),
        "/repos/test-org/repo-a/pulls/8": _FakeResponse(200, _gh_pr(8, new_sha)),
    })
    enqueue = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
    _patch_sync_engine(monkeypatch, test_db, client_fake=client, enqueue_mock=enqueue)

    counts = await sync_engine.sync_prs_once("startup")

    assert counts["jobs_enqueued"] == 1
    assert enqueue.call_args.kwargs["webhook_action"] == "synchronize"
    pr = (await test_db.execute(
        select(PullRequest).where(PullRequest.pr_number == 8)
    )).scalars().first()
    assert pr.head_sha == new_sha


@pytest.mark.asyncio
async def test_pr_pass_same_sha_is_noop(test_db, mock_user, monkeypatch):
    inst, repo = await _install_repo(test_db, mock_user, gid=1001, full_name="test-org/repo-a")
    sha = "e" * 40
    await _add_pr(test_db, repo, 9, sha)
    client = _FakeClient({
        "/repos/test-org/repo-a/pulls": _FakeResponse(200, [_gh_pr(9, sha)]),
    })
    enqueue = AsyncMock()
    _patch_sync_engine(monkeypatch, test_db, client_fake=client, enqueue_mock=enqueue)

    counts = await sync_engine.sync_prs_once("startup")

    assert counts["jobs_enqueued"] == 0
    enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_pr_pass_skips_when_commit_already_reviewed(test_db, mock_user, monkeypatch):
    """Webhook already reviewed this commit — sync must NOT enqueue a duplicate."""
    inst, repo = await _install_repo(test_db, mock_user, gid=1001, full_name="test-org/repo-a")
    old_sha = "f" * 40
    new_sha = "aa" * 20
    pr = await _add_pr(test_db, repo, 10, old_sha)
    review = Review(pr_id=pr.id, status="completed")
    test_db.add(review)
    await test_db.commit()
    await test_db.refresh(review)
    test_db.add(ReviewExecution(
        review_id=review.id,
        execution_number=1,
        trigger="webhook",
        status="completed",
        commit_sha=new_sha,
    ))
    await test_db.commit()

    client = _FakeClient({
        "/repos/test-org/repo-a/pulls": _FakeResponse(200, [_gh_pr(10, new_sha)]),
    })
    enqueue = AsyncMock()
    _patch_sync_engine(monkeypatch, test_db, client_fake=client, enqueue_mock=enqueue)

    counts = await sync_engine.sync_prs_once("startup")

    assert counts["jobs_enqueued"] == 0
    enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_pr_pass_active_review_blocks_new_commit_sync(test_db, mock_user, monkeypatch):
    """In-flight review on the PR: sync only emits synchronize for new commits
    (dispatcher supersedes in-flight work) — the new commit still gets one job."""
    inst, repo = await _install_repo(test_db, mock_user, gid=1001, full_name="test-org/repo-a")
    old_sha = "a1" * 20
    new_sha = "b2" * 20
    pr = await _add_pr(test_db, repo, 11, old_sha)
    review = Review(pr_id=pr.id, status="running")
    test_db.add(review)
    await test_db.commit()

    client = _FakeClient({
        "/repos/test-org/repo-a/pulls": _FakeResponse(200, [_gh_pr(11, new_sha)]),
        "/repos/test-org/repo-a/pulls/11": _FakeResponse(200, _gh_pr(11, new_sha)),
    })
    enqueue = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
    _patch_sync_engine(monkeypatch, test_db, client_fake=client, enqueue_mock=enqueue)

    counts = await sync_engine.sync_prs_once("startup")

    assert counts["jobs_enqueued"] == 1
    assert enqueue.call_args.kwargs["webhook_action"] == "synchronize"


@pytest.mark.asyncio
async def test_pr_pass_closed_reconcile(test_db, mock_user, monkeypatch):
    inst, repo = await _install_repo(test_db, mock_user, gid=1001, full_name="test-org/repo-a")
    sha = "c3" * 20
    await _add_pr(test_db, repo, 12, sha)  # DB says open; GitHub says closed
    client = _FakeClient({
        "/repos/test-org/repo-a/pulls": _FakeResponse(200, []),  # no open PRs
        "/repos/test-org/repo-a/pulls/12": _FakeResponse(200, _gh_pr(12, sha, state="closed", merged=True)),
    })
    enqueue = AsyncMock()
    _patch_sync_engine(monkeypatch, test_db, client_fake=client, enqueue_mock=enqueue)

    counts = await sync_engine.sync_prs_once("startup")

    assert counts["prs_updated"] >= 1
    pr = (await test_db.execute(
        select(PullRequest).where(PullRequest.pr_number == 12)
    )).scalars().first()
    assert pr.status == "merged"


@pytest.mark.asyncio
async def test_pr_pass_gated_when_permissions_missing(test_db, mock_user, monkeypatch):
    inst, repo = await _install_repo(test_db, mock_user, gid=1001, full_name="test-org/repo-a",
                                     permissions_ok=False)
    client = _FakeClient({
        "/repos/test-org/repo-a/pulls": _FakeResponse(200, [_gh_pr(13, "d4" * 20)]),
    })
    enqueue = AsyncMock()
    _patch_sync_engine(monkeypatch, test_db, client_fake=client, enqueue_mock=enqueue)

    counts = await sync_engine.sync_prs_once("startup")

    assert counts["prs_found"] == 0
    assert counts["jobs_enqueued"] == 0
    enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_pr_pass_skips_removed_and_disabled_repos(test_db, mock_user, monkeypatch):
    inst1, repo_active = await _install_repo(test_db, mock_user, gid=1001, full_name="test-org/repo-a")
    inst2, repo_removed = await _install_repo(test_db, mock_user, gid=1002, full_name="test-org/repo-b",
                                              removed_at=datetime.now(timezone.utc))
    inst3, repo_disabled = await _install_repo(test_db, mock_user, gid=1003, full_name="test-org/repo-c",
                                               reviews_enabled=False)
    client = _FakeClient({
        "/repos/test-org/repo-a/pulls": _FakeResponse(200, [_gh_pr(14, "e5" * 20)]),
    })
    enqueue = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
    _patch_sync_engine(monkeypatch, test_db, client_fake=client, enqueue_mock=enqueue)

    counts = await sync_engine.sync_prs_once("startup")

    assert counts["prs_found"] == 1  # only repo-a processed
    assert counts["jobs_enqueued"] == 1


@pytest.mark.asyncio
async def test_pr_pass_per_repo_isolation(test_db, mock_user, monkeypatch):
    """Repo #1 timing out must not stop repo #2."""
    inst1, repo1 = await _install_repo(test_db, mock_user, gid=2001, full_name="test-org/broken")
    inst2, repo2 = await _install_repo(test_db, mock_user, gid=2002, full_name="test-org/healthy")

    class _FailingClient(_FakeClient):
        async def get(self, url, *args, **kwargs):
            if "/repos/test-org/broken/" in url:
                raise RuntimeError("GitHub timeout")
            return await super().get(url, *args, **kwargs)

    client = _FailingClient({
        "/repos/test-org/healthy/pulls": _FakeResponse(200, [_gh_pr(15, "f6" * 20)]),
    })
    enqueue = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
    _patch_sync_engine(monkeypatch, test_db, client_fake=client, enqueue_mock=enqueue)

    counts = await sync_engine.sync_prs_once("startup")

    assert counts["prs_found"] == 1
    assert counts["jobs_enqueued"] == 1
    assert "test-org/broken" in counts["failures"]


@pytest.mark.asyncio
async def test_pr_pass_tier_skips_recent_repo_in_background(test_db, mock_user, monkeypatch):
    """Background pass: recently synced repo with no open PRs is not due."""
    inst, repo = await _install_repo(
        test_db, mock_user, gid=1001, full_name="test-org/repo-a",
        last_synced_at=datetime.now(timezone.utc),
    )
    client = _FakeClient({})
    enqueue = AsyncMock()
    _patch_sync_engine(monkeypatch, test_db, client_fake=client, enqueue_mock=enqueue)

    counts = await sync_engine.sync_prs_once("background")

    assert counts["prs_found"] == 0
    assert counts["jobs_enqueued"] == 0
    enqueue.assert_not_called()


# ---------------------------------------------------------------------------
# Full pass + sync_runs audit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_sync_pass_records_sync_run(test_db, mock_user, monkeypatch):
    inst, repo = await _install_repo(test_db, mock_user, gid=1001, full_name="test-org/repo-a")
    sha = "ab" * 20
    client = _FakeClient({
        "/installation/repositories": _FakeResponse(200, {"repositories": [_gh_repo(1001, "test-org/repo-a")]}),
        "/repos/test-org/repo-a/pulls": _FakeResponse(200, [_gh_pr(16, sha)]),
        "/repos/test-org/repo-a/pulls/16": _FakeResponse(200, _gh_pr(16, sha)),
    })
    enqueue = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
    _patch_sync_engine(monkeypatch, test_db, client_fake=client, enqueue_mock=enqueue)

    result = await sync_engine.run_sync_pass("startup", user_id=mock_user.id, use_advisory_lock=False)

    assert result["status"] == "success"
    assert result["counts"]["jobs_enqueued"] == 1
    runs = (await test_db.execute(
        select(SyncRun).order_by(SyncRun.started_at.desc())
    )).scalars().all()
    assert len(runs) >= 1
    run = runs[0]
    assert run.reason == "startup"
    assert run.status == "success"
    assert run.repos_added == 0
    assert run.jobs_enqueued == 1


@pytest.mark.asyncio
async def test_run_sync_pass_records_partial(test_db, mock_user, monkeypatch):
    inst, repo = await _install_repo(test_db, mock_user, gid=1001, full_name="test-org/broken")

    class _BrokenClient(_FakeClient):
        async def get(self, url, *args, **kwargs):
            raise RuntimeError("GitHub timeout")

    _patch_sync_engine(monkeypatch, test_db, client_fake=_BrokenClient({}))

    result = await sync_engine.run_sync_pass("startup", user_id=mock_user.id, use_advisory_lock=False)

    assert result["status"] == "partial"
    runs = (await test_db.execute(
        select(SyncRun).order_by(SyncRun.started_at.desc())
    )).scalars().all()
    run = runs[0]
    assert run.status == "partial"
    assert run.repos_failed >= 1
    assert run.details is not None
