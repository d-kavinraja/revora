"""Regression tests: manual repository sync is fast, background, and eligible-only.

`POST /repositories/{id}/sync` must return 202 immediately regardless of PR
count; the background pass (sync engine: open-only, paginated, per-PR
isolated) must create Review/ReviewExecution/ReviewJob rows exclusively for
currently OPEN PRs. Historical closed/merged PRs get metadata-only treatment.

Covers:
 A. Repository with only merged PRs -> 0 Reviews/Executions/Jobs
 B. Mixed closed/merged/open PRs -> only OPEN PRs become candidates
 C. Bot comment on closed/merged PR -> no imported Review
 D. Bot comment on open PR -> normal pipeline review (no legacy import)
 E. Closed PR reopened with no prior Review -> first Review + execution
 F. Reviewed PR closed then reopened -> SAME Review + new execution
 G. Repeated sync -> no duplicates
 H. Sync + webhook race -> no duplicate Review for same PR/SHA
 5. Per-PR GitHub failure -> independent PRs still processed
 10. Endpoint returns 202 before background work runs (no 15s browser wait)
"""

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.execution import ReviewExecution
from app.models.github import Installation, PullRequest, Repository
from app.models.review import Review
from app.models.user import User
from app.queue.models import ReviewJob

FULL_NAME = "testowner/test-repo"
GITHUB_ID = 777
INSTALLATION_ID = 424242
SHA = "c" * 40


class _FakeResponse:
    def __init__(self, json_data=None, status_code=200):
        self._json = json_data
        self.status_code = status_code

    @property
    def is_success(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._json


class _EngineFakeClient:
    """Fake httpx.AsyncClient speaking the sync-engine URL shapes.

    open_prs: list of (number, sha) tuples returned by the open-PR list.
    details: dict number -> {"additions":..,"merged":..} for /pulls/{n}.
    fail_detail_for: PR numbers whose detail fetch raises (per-PR isolation).
    """

    def __init__(self, open_prs, details=None, fail_detail_for=()):
        self._open_prs = open_prs
        self._details = details or {}
        self._fail_detail_for = set(fail_detail_for)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, *args, **kwargs):
        if url.endswith("/pulls"):
            return _FakeResponse(
                [
                    {
                        "number": n, "title": f"PR {n}", "state": "open",
                        "body": "", "user": {"login": "author"},
                        "head": {"sha": sha, "ref": "feat"},
                        "base": {"ref": "main"}, "draft": False,
                    }
                    for n, sha in self._open_prs
                ]
            )
        number = int(url.rstrip("/").split("/")[-1])
        if number in self._fail_detail_for:
            raise RuntimeError("GitHub timeout")
        return _FakeResponse(
            self._details.get(
                number,
                {"additions": 1, "deletions": 0, "changed_files": 1},
            )
        )


class _FakeBackgroundTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, func, *args, **kwargs):
        self.tasks.append((func, args, kwargs))


@pytest.fixture
def session_factory(test_engine, monkeypatch):
    factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    monkeypatch.setattr("app.github.shared.AsyncSessionLocal", factory)
    monkeypatch.setattr("app.db.session.AsyncSessionLocal", factory)
    # worker.py bound AsyncSessionLocal directly at import; patch its name too
    # so recover_orphaned_jobs under test hits the test database.
    monkeypatch.setattr("app.queue.worker.AsyncSessionLocal", factory)
    return factory


@pytest.fixture(autouse=True)
async def clean_tables(session_factory):
    from app.models.sync_run import SyncRun

    yield
    async with session_factory() as db:
        for model in (
            ReviewExecution,
            Review,
            PullRequest,
            Repository,
            Installation,
            ReviewJob,
            SyncRun,
            User,
        ):
            await db.execute(model.__table__.delete())
        await db.commit()


async def _seed_repo(session_factory):
    async with session_factory() as db:
        user = User(
            id=uuid.uuid4(), name="T", email="t@example.com",
            role="user", is_verified=True,
        )
        db.add(user)
        inst = Installation(
            id=uuid.uuid4(), installation_id=INSTALLATION_ID, account_id=1,
            account_login="testowner", account_type="User", user_id=user.id,
            repository_selection="all", permissions={}, events={},
            permissions_ok=True,
        )
        db.add(inst)
        repo = Repository(
            id=uuid.uuid4(), github_id=GITHUB_ID, name="test-repo",
            full_name=FULL_NAME, is_private=False, installation_id=inst.id,
            reviews_enabled=True,
        )
        db.add(repo)
        await db.commit()
        await db.refresh(repo)
        return {"user": user, "repo": repo}


def _patch_endpoint(monkeypatch):
    import app.api.v1.endpoints.repositories as repo_endpoint

    monkeypatch.setattr(
        repo_endpoint.github_app_auth,
        "get_installation_token",
        AsyncMock(return_value="tok"),
    )


def _patch_engine(monkeypatch, client):
    from app.services import sync_engine

    monkeypatch.setattr(
        sync_engine.github_app_auth,
        "get_installation_token",
        AsyncMock(return_value="tok"),
    )
    monkeypatch.setattr(
        sync_engine.httpx, "AsyncClient", lambda *a, **k: client
    )


async def _run_sync(session_factory, repo_id, user):
    """Call the endpoint (expect 202), then run the captured background task."""
    from app.api.v1.endpoints.repositories import sync_repository

    tasks = _FakeBackgroundTasks()
    async with session_factory() as db:
        response = await sync_repository(str(repo_id), tasks, db, user)
    assert response["status"] == "accepted"
    assert len(tasks.tasks) == 1
    func, args, kwargs = tasks.tasks[0]
    return await func(*args, **kwargs)


async def _counts(session_factory):
    async with session_factory() as db:
        out = {}
        for name, model in (
            ("prs", PullRequest), ("reviews", Review),
            ("executions", ReviewExecution), ("jobs", ReviewJob),
        ):
            out[name] = (
                await db.execute(select(func.count()).select_from(model))
            ).scalar()
        return out


def _webhook_payload(pr_number, sha=SHA):
    return {
        "installation": {"id": INSTALLATION_ID},
        "repository": {
            "owner": {"login": "testowner"}, "name": "test-repo",
            "full_name": FULL_NAME, "private": False, "id": GITHUB_ID,
        },
        "pull_request": {
            "number": pr_number, "title": f"PR {pr_number}", "body": "",
            "head": {"sha": sha, "ref": "feat"}, "base": {"ref": "main"},
            "user": {"login": "author"}, "additions": 1, "deletions": 0,
            "changed_files": 1,
        },
    }


class TestBackgroundSyncEligibility:
    async def test_10_returns_202_before_work_runs(
        self, session_factory, monkeypatch
    ):
        """The HTTP response must not wait for PR processing (no 15s timeout)."""
        from app.api.v1.endpoints.repositories import sync_repository

        seed = await _seed_repo(session_factory)
        _patch_endpoint(monkeypatch)
        tasks = _FakeBackgroundTasks()
        async with session_factory() as db:
            response = await sync_repository(str(seed["repo"].id), tasks, db, seed["user"])

        assert response["status"] == "accepted"
        assert len(tasks.tasks) == 1
        # Nothing processed yet: response returned before background work.
        assert await _counts(session_factory) == {
            "prs": 0, "reviews": 0, "executions": 0, "jobs": 0,
        }

    async def test_A_only_merged_prs_create_nothing(
        self, session_factory, monkeypatch
    ):
        seed = await _seed_repo(session_factory)
        _patch_endpoint(monkeypatch)
        _patch_engine(monkeypatch, _EngineFakeClient(open_prs=[]))
        counts = await _run_sync(session_factory, seed["repo"].id, seed["user"])

        assert counts["jobs_enqueued"] == 0
        assert await _counts(session_factory) == {
            "prs": 0, "reviews": 0, "executions": 0, "jobs": 0,
        }

    async def test_B_mixed_prs_only_open_reviewed(
        self, session_factory, monkeypatch
    ):
        seed = await _seed_repo(session_factory)
        _patch_endpoint(monkeypatch)
        # Engine list is open-only: 53 and 55. Closed/merged 50/51/52/54 are
        # never even fetched, so they cannot create reviews/jobs.
        _patch_engine(
            monkeypatch, _EngineFakeClient(open_prs=[(53, "8" * 40), (55, "a" * 40)])
        )
        counts = await _run_sync(session_factory, seed["repo"].id, seed["user"])

        assert counts["jobs_enqueued"] == 2
        async with session_factory() as db:
            pr_rows = (
                await db.execute(select(PullRequest).order_by(PullRequest.pr_number))
            ).scalars().all()
            assert [p.pr_number for p in pr_rows] == [53, 55]
            assert all(p.status == "open" for p in pr_rows)
        totals = await _counts(session_factory)
        assert totals["reviews"] == 2
        assert totals["executions"] == 2
        assert totals["jobs"] == 2

    async def test_C_closed_prs_never_fetched_or_imported(
        self, session_factory, monkeypatch
    ):
        seed = await _seed_repo(session_factory)
        _patch_endpoint(monkeypatch)
        _patch_engine(monkeypatch, _EngineFakeClient(open_prs=[]))
        await _run_sync(session_factory, seed["repo"].id, seed["user"])

        assert await _counts(session_factory) == {
            "prs": 0, "reviews": 0, "executions": 0, "jobs": 0,
        }

    async def test_D_open_pr_gets_pipeline_review(
        self, session_factory, monkeypatch
    ):
        seed = await _seed_repo(session_factory)
        _patch_endpoint(monkeypatch)
        _patch_engine(monkeypatch, _EngineFakeClient(open_prs=[(55, "a" * 40)]))
        await _run_sync(session_factory, seed["repo"].id, seed["user"])

        totals = await _counts(session_factory)
        assert totals["reviews"] == 1
        assert totals["executions"] == 1
        assert totals["jobs"] == 1
        async with session_factory() as db:
            review = (await db.execute(select(Review))).scalars().first()
            assert review.status == "pending"

    async def test_E_reopened_no_prior_review_gets_first_review(
        self, session_factory, monkeypatch
    ):
        seed = await _seed_repo(session_factory)
        async with session_factory() as db:
            db.add(
                PullRequest(
                    repo_id=seed["repo"].id, pr_number=52, title="PR 52",
                    author="author", head_sha=SHA, base_branch="main",
                    head_branch="feat", status="closed",
                )
            )
            await db.commit()

        _patch_endpoint(monkeypatch)
        _patch_engine(monkeypatch, _EngineFakeClient(open_prs=[(52, SHA)]))
        await _run_sync(session_factory, seed["repo"].id, seed["user"])

        async with session_factory() as db:
            pr = (
                await db.execute(
                    select(PullRequest).where(PullRequest.pr_number == 52)
                )
            ).scalars().first()
            assert pr.status == "open"
            reviews = (
                await db.execute(select(Review).where(Review.pr_id == pr.id))
            ).scalars().all()
            assert len(reviews) == 1
            execs = (
                await db.execute(
                    select(ReviewExecution).where(
                        ReviewExecution.review_id == reviews[0].id
                    )
                )
            ).scalars().all()
            assert len(execs) == 1

    async def test_5_per_pr_failure_does_not_abort_sync(
        self, session_factory, monkeypatch
    ):
        seed = await _seed_repo(session_factory)
        _patch_endpoint(monkeypatch)
        _patch_engine(
            monkeypatch,
            _EngineFakeClient(
                open_prs=[(53, "8" * 40), (55, "a" * 40)],
                fail_detail_for=(53,),
            ),
        )
        counts = await _run_sync(session_factory, seed["repo"].id, seed["user"])

        assert counts["jobs_enqueued"] == 1
        assert "testowner/test-repo#53" in counts["failures"]
        totals = await _counts(session_factory)
        assert totals["jobs"] == 1

    async def test_G_repeated_sync_no_duplicates(
        self, session_factory, monkeypatch
    ):
        seed = await _seed_repo(session_factory)
        _patch_endpoint(monkeypatch)
        _patch_engine(monkeypatch, _EngineFakeClient(open_prs=[(53, "8" * 40)]))
        await _run_sync(session_factory, seed["repo"].id, seed["user"])
        first = await _counts(session_factory)
        await _run_sync(session_factory, seed["repo"].id, seed["user"])
        second = await _counts(session_factory)
        assert first == second
        assert second["reviews"] == 1
        assert second["jobs"] == 1

    async def test_H_sync_then_webhook_no_duplicate(
        self, session_factory, monkeypatch
    ):
        from app.queue.dispatcher import enqueue_review_job

        seed = await _seed_repo(session_factory)
        sha = "8" * 40
        _patch_endpoint(monkeypatch)
        _patch_engine(monkeypatch, _EngineFakeClient(open_prs=[(53, sha)]))
        await _run_sync(session_factory, seed["repo"].id, seed["user"])
        before = await _counts(session_factory)
        assert before["reviews"] == 1

        async with session_factory() as db:
            job = await enqueue_review_job(
                db, _webhook_payload(53, sha), "webhook-redelivery",
                webhook_action="opened",
            )
            assert job is None

        assert await _counts(session_factory) == before


class TestReopenAfterSync:
    async def test_F_reviewed_closed_reopened_reuses_review(
        self, session_factory, monkeypatch
    ):
        from app.queue.dispatcher import enqueue_review_job
        from app.services.review_execution_service import (
            create_execution,
            mark_execution_final,
        )

        seed = await _seed_repo(session_factory)
        old_sha, new_sha = "b" * 40, SHA
        async with session_factory() as db:
            pr = PullRequest(
                repo_id=seed["repo"].id, pr_number=52, title="PR 52",
                author="author", head_sha=old_sha, base_branch="main",
                head_branch="feat", status="closed",
            )
            db.add(pr)
            await db.flush()
            review = Review(pr_id=pr.id, status="completed")
            db.add(review)
            await db.flush()
            await create_execution(
                db, review.id, trigger="webhook", commit_sha=old_sha
            )
            await mark_execution_final(db, review.id, "completed")
            await db.commit()
            review_id, pr_id = review.id, pr.id

        async with session_factory() as db:
            job = await enqueue_review_job(
                db, _webhook_payload(52, new_sha), "delivery-reopen",
                webhook_action="reopened",
            )
            assert job is not None

        async with session_factory() as db:
            reviews = (
                await db.execute(select(Review).where(Review.pr_id == pr_id))
            ).scalars().all()
            assert len(reviews) == 1
            assert reviews[0].id == review_id
            assert reviews[0].status == "pending"
            execs = (
                await db.execute(
                    select(ReviewExecution)
                    .where(ReviewExecution.review_id == review_id)
                    .order_by(ReviewExecution.execution_number)
                )
            ).scalars().all()
            assert len(execs) == 2
            assert execs[1].trigger == "reopened"
            assert execs[1].commit_sha == new_sha


class TestDiscoveryBarrier:
    """P0-1: a repository's discovery batch must become visible atomically.

    The worker (separate session) must never observe PR #1 as Pending/queued
    while PRs #2/#3 do not exist yet.
    """

    async def test_batch_invisible_until_caller_commit(
        self, session_factory, monkeypatch
    ):
        from datetime import UTC, datetime

        from app.services import sync_engine

        seed = await _seed_repo(session_factory)
        # Fake GitHub returns newest-first (like the real API default).
        _patch_engine(
            monkeypatch,
            _EngineFakeClient(
                open_prs=[(55, "9" * 40), (54, "7" * 40), (53, "8" * 40)]
            ),
        )
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        counts = {
            "prs_found": 0, "prs_updated": 0,
            "jobs_enqueued": 0, "failures": {},
        }
        db = session_factory()
        # Count real commits during discovery: the barrier requires ZERO —
        # everything stays flushed-but-uncommitted until the caller's single
        # batch commit. (On a separate DB connection, uncommitted rows are
        # invisible, so the worker cannot observe a partial Pending set.
        # This harness shares one in-memory connection, hence we assert the
        # mechanism — no commit — instead of cross-connection invisibility.)
        commits = []
        real_commit = db.commit

        async def counting_commit():
            commits.append(1)
            return await real_commit()

        monkeypatch.setattr(db, "commit", counting_commit)
        try:
            repo = await db.get(Repository, seed["repo"].id)
            inst = await db.get(Installation, repo.installation_id)
            found, updated, enqueued = await sync_engine._sync_repository_prs(
                db, repo, inst, headers, counts, datetime.now(UTC)
            )
            assert (found, enqueued) == (3, 3)
            assert commits == [], (
                "discovery must not commit per-PR; "
                f"saw {len(commits)} commit(s) mid-batch"
            )
            # Same session sees its flushed batch...
            here = (
                await db.execute(select(func.count()).select_from(ReviewJob))
            ).scalar()
            assert here == 3
            # The caller's single commit publishes the whole batch at once.
            await real_commit()
        finally:
            await db.close()

        async with session_factory() as db3:
            jobs = (
                await db3.execute(select(func.count()).select_from(ReviewJob))
            ).scalar()
            reviews = (
                await db3.execute(select(func.count()).select_from(Review))
            ).scalar()
            assert (jobs, reviews) == (3, 3)
            pending = (
                await db3.execute(
                    select(func.count())
                    .select_from(Review)
                    .where(Review.status == "pending")
                )
            ).scalar()
            assert pending == 3

    async def test_oldest_first_enqueue_order(
        self, session_factory, monkeypatch
    ):
        from app.queue.models import JobStatus

        seed = await _seed_repo(session_factory)
        _patch_endpoint(monkeypatch)
        # Newest-first from GitHub, like the real API default.
        _patch_engine(
            monkeypatch,
            _EngineFakeClient(
                open_prs=[(55, "9" * 40), (54, "7" * 40), (53, "8" * 40)]
            ),
        )
        await _run_sync(session_factory, seed["repo"].id, seed["user"])

        # FIFO (created_at ASC) must drain oldest-first: #53 → #54 → #55.
        async with session_factory() as db:
            rows = (
                await db.execute(
                    select(ReviewJob.pr_number)
                    .where(ReviewJob.status == JobStatus.QUEUED)
                    .order_by(ReviewJob.created_at.asc())
                )
            ).scalars().all()
            assert list(rows) == [53, 54, 55]


class TestDuplicateSyncGuard:
    """P0-4: refresh/double-click must not duplicate a running sync."""

    async def _call_endpoint(self, session_factory, repo_id, user):
        from app.api.v1.endpoints.repositories import sync_repository

        tasks = _FakeBackgroundTasks()
        async with session_factory() as db:
            response = await sync_repository(str(repo_id), tasks, db, user)
        return response, tasks

    async def test_second_sync_while_running_returns_in_progress(
        self, session_factory, monkeypatch
    ):
        from app.models.sync_run import SyncRun

        seed = await _seed_repo(session_factory)
        _patch_endpoint(monkeypatch)
        _patch_engine(monkeypatch, _EngineFakeClient(open_prs=[(53, "8" * 40)]))

        first, tasks = await self._call_endpoint(
            session_factory, seed["repo"].id, seed["user"]
        )
        assert first["status"] == "accepted"
        assert "run_id" in first

        # Without running the background task, a second request (browser
        # refresh resend / double-click) must NOT schedule duplicate work.
        second, tasks2 = await self._call_endpoint(
            session_factory, seed["repo"].id, seed["user"]
        )
        assert second["status"] == "in_progress"
        assert len(tasks2.tasks) == 0

        # Running the captured task finalizes the run as success.
        func, args, kwargs = tasks.tasks[0]
        await func(*args, **kwargs)
        async with session_factory() as db:
            run = (await db.execute(select(SyncRun))).scalars().all()
            by_repo = [
                r
                for r in run
                if (r.details or {}).get("repo_id") == str(seed["repo"].id)
            ]
            assert len(by_repo) == 1
            assert by_repo[0].status == "success"
            assert by_repo[0].completed_at is not None

        # After completion a new sync is accepted again.
        third, tasks3 = await self._call_endpoint(
            session_factory, seed["repo"].id, seed["user"]
        )
        assert third["status"] == "accepted"

    async def test_stale_running_sync_is_finalized_and_proceeds(
        self, session_factory, monkeypatch
    ):
        from datetime import UTC, datetime, timedelta

        from app.models.sync_run import SyncRun

        seed = await _seed_repo(session_factory)
        _patch_endpoint(monkeypatch)
        async with session_factory() as db:
            db.add(
                SyncRun(
                    reason="manual",
                    triggered_by=seed["user"].id,
                    started_at=datetime.now(UTC) - timedelta(minutes=61),
                    status="running",
                    details={"repo_id": str(seed["repo"].id)},
                )
            )
            await db.commit()

        response, tasks = await self._call_endpoint(
            session_factory, seed["repo"].id, seed["user"]
        )
        # Stale orphan (e.g. backend died mid-sync) does not block: the new
        # sync is accepted and the stale row is marked failed.
        assert response["status"] == "accepted"
        async with session_factory() as db:
            runs = (await db.execute(select(SyncRun))).scalars().all()
            by_repo = [
                r
                for r in runs
                if (r.details or {}).get("repo_id") == str(seed["repo"].id)
            ]
            statuses = sorted(r.status for r in by_repo)
            assert statuses == ["failed", "running"]


class TestHealthyBacklogSurvives:
    """P0-2: old-but-waiting queued jobs are healthy backlog, not orphans."""

    async def _seed_queued(
        self, session_factory, repo, minutes_old, pr_number, sha
    ):
        from datetime import UTC, datetime, timedelta

        from app.queue.models import JobStatus

        async with session_factory() as db:
            db.add(
                ReviewJob(
                    delivery_id=f"old-{uuid.uuid4()}",
                    head_sha=sha,
                    pr_number=pr_number,
                    repo_id=repo.id,
                    payload={},
                    status=JobStatus.QUEUED,
                    created_at=datetime.now(UTC) - timedelta(minutes=minutes_old),
                )
            )
            await db.commit()

    async def test_queued_behind_running_job_is_kept(
        self, session_factory, monkeypatch
    ):
        from app.queue import worker as worker_mod
        from app.queue.models import JobStatus

        seed = await _seed_repo(session_factory)
        await self._seed_queued(session_factory, seed["repo"], 60, 51, "1" * 40)
        async with session_factory() as db:
            db.add(
                ReviewJob(
                    delivery_id=f"run-{uuid.uuid4()}",
                    head_sha="2" * 40,
                    pr_number=52,
                    repo_id=seed["repo"].id,
                    payload={},
                    status=JobStatus.RUNNING,
                )
            )
            await db.commit()

        await worker_mod.recover_orphaned_jobs(queue_timeout_minutes=30)

        async with session_factory() as db:
            queued = (
                await db.execute(
                    select(func.count())
                    .select_from(ReviewJob)
                    .where(ReviewJob.status == JobStatus.QUEUED)
                )
            ).scalar()
            assert queued == 1

    async def test_queued_with_recent_claim_is_kept(
        self, session_factory, monkeypatch
    ):
        from datetime import UTC, datetime

        from app.queue import worker as worker_mod
        from app.queue.models import JobStatus

        seed = await _seed_repo(session_factory)
        await self._seed_queued(session_factory, seed["repo"], 60, 51, "1" * 40)
        # The worker claimed something a minute ago: it is draining, the
        # 60-minute-old queued job is healthy backlog.
        monkeypatch.setattr(
            worker_mod, "_last_claim_at", datetime.now(UTC)
        )
        monkeypatch.setattr(worker_mod, "_worker_started_at", None)

        await worker_mod.recover_orphaned_jobs(queue_timeout_minutes=30)

        async with session_factory() as db:
            queued = (
                await db.execute(
                    select(func.count())
                    .select_from(ReviewJob)
                    .where(ReviewJob.status == JobStatus.QUEUED)
                )
            ).scalar()
            assert queued == 1

    async def test_truly_stuck_queue_still_recovers(
        self, session_factory, monkeypatch
    ):
        from app.queue import worker as worker_mod
        from app.queue.models import JobStatus

        seed = await _seed_repo(session_factory)
        await self._seed_queued(session_factory, seed["repo"], 60, 51, "1" * 40)
        # No running jobs anywhere, worker never claimed anything (e.g. a
        # standalone recovery check): the stale job is genuinely stuck.
        monkeypatch.setattr(worker_mod, "_last_claim_at", None)
        monkeypatch.setattr(worker_mod, "_worker_started_at", None)

        await worker_mod.recover_orphaned_jobs(queue_timeout_minutes=30)

        async with session_factory() as db:
            failed = (
                await db.execute(
                    select(func.count())
                    .select_from(ReviewJob)
                    .where(ReviewJob.status == JobStatus.FAILED)
                )
            ).scalar()
            assert failed == 1


class TestSyncAllBackground:
    """P0-3: sync-all must return 202 without doing the work in-request."""

    async def test_sync_all_returns_202_and_delegates(
        self, session_factory, monkeypatch
    ):
        from unittest.mock import AsyncMock

        from app.api.v1.endpoints import repositories as repo_endpoint
        from app.services import repository_service as repository_service_mod

        seed = await _seed_repo(session_factory)
        tasks = _FakeBackgroundTasks()
        response = await repo_endpoint.sync_all_repositories(
            tasks, seed["user"]
        )
        assert response["status"] == "accepted"
        assert len(tasks.tasks) == 1

        # The captured background task performs the actual pass (mocked here
        # to avoid live GitHub; delegation itself is what this asserts).
        refresh = AsyncMock(
            return_value={"status": "success", "counts": {}}
        )
        monkeypatch.setattr(
            repository_service_mod.repository_service,
            "refresh_installation",
            refresh,
        )
        func, args, kwargs = tasks.tasks[0]
        result = await func(*args, **kwargs)
        assert result["status"] == "success"
        refresh.assert_called_once()
