"""Regression tests: global serial review execution (concurrency = 1).

Covers:
  1. Two repositories with queued jobs → only ONE RUNNING globally.
  2. One repository with multiple jobs → only ONE RUNNING.
  3. Repo A multiple jobs + Repo B 1 job → Repo B gets the next turn
     after A's running job completes (fair cross-repo scheduling).
  4. Two workers attempting to claim simultaneously → only one succeeds.
  5. Running job blocks additional claims globally.
  6. Completed job releases the global slot.
  7. Failed job releases the global slot.
  8. Cancelled job releases the global slot.
  9. Stale/recovered job does not create duplicate execution.
  10. Backend restart recovers correctly (startup recovery + reclaim).
  11. Existing per-repository FIFO remains intact.
  12. Existing webhook/reopen/rerun/retry shape remains intact.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.github import Installation, PullRequest, Repository
from app.models.review import Review
from app.models.user import User
from app.queue.models import JobStatus, ReviewJob

WORKER_PATH = Path(__file__).parent.parent / "app" / "queue" / "worker.py"
DISPATCHER_PATH = Path(__file__).parent.parent / "app" / "queue" / "dispatcher.py"
ROOT = Path(__file__).parents[2]


@pytest.fixture
def session_factory(test_engine, monkeypatch):
    from app.queue import worker as worker_mod

    factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    monkeypatch.setattr("app.db.session.AsyncSessionLocal", factory)
    monkeypatch.setattr("app.queue.worker.AsyncSessionLocal", factory)
    # Isolate recovery liveness anchors so this module cannot leak into
    # other suites (queued-timeout recovery is skipped when the worker
    # looks "recently started").
    monkeypatch.setattr(worker_mod, "_worker_started_at", None)
    monkeypatch.setattr(worker_mod, "_last_claim_at", None)
    return factory


@pytest.fixture(autouse=True)
async def clean_tables(session_factory):
    from app.models.execution import ReviewExecution
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


async def _seed_repo(session_factory, *, name: str, gid: int, install_id: int):
    async with session_factory() as db:
        user = User(
            id=uuid.uuid4(),
            name="T",
            email=f"{name}@example.com",
            role="user",
            is_verified=True,
        )
        db.add(user)
        inst = Installation(
            id=uuid.uuid4(),
            installation_id=install_id,
            account_id=1,
            account_login="testowner",
            account_type="User",
            user_id=user.id,
            repository_selection="all",
            permissions={},
            events={},
            permissions_ok=True,
        )
        db.add(inst)
        repo = Repository(
            id=uuid.uuid4(),
            github_id=gid,
            name=name,
            full_name=f"testowner/{name}",
            is_private=False,
            installation_id=inst.id,
            reviews_enabled=True,
        )
        db.add(repo)
        await db.commit()
        await db.refresh(repo)
        return repo


async def _seed_job(
    session_factory,
    repo,
    pr_number: int,
    *,
    status=JobStatus.QUEUED,
    created_at: datetime | None = None,
    completed_at: datetime | None = None,
    head_sha: str | None = None,
):
    async with session_factory() as db:
        job = ReviewJob(
            delivery_id=f"gid-{uuid.uuid4()}",
            head_sha=head_sha or (f"{pr_number:02d}" * 20)[:40],
            pr_number=pr_number,
            repo_id=repo.id,
            payload={},
            status=status,
            created_at=created_at or datetime.now(UTC),
            completed_at=completed_at,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job


async def _running_count(session_factory) -> int:
    async with session_factory() as db:
        return (
            await db.execute(
                select(func.count())
                .select_from(ReviewJob)
                .where(ReviewJob.status == JobStatus.RUNNING)
            )
        ).scalar() or 0


async def _set_status(session_factory, job_id, status, **extra):
    async with session_factory() as db:
        job = await db.get(ReviewJob, job_id)
        job.status = status
        for k, v in extra.items():
            setattr(job, k, v)
        db.add(job)
        await db.commit()


async def _claim(session_factory):
    from app.queue.worker import claim_next_job

    async with session_factory() as session:
        return await claim_next_job(session)


async def _claim_locked(session_factory):
    from app.queue.worker import claim_next_job_with_factory

    return await claim_next_job_with_factory(session_factory)


class TestGlobalSerialClaim:
    async def test_two_repos_only_one_running(self, session_factory):
        """1. Two repositories with queued jobs → only ONE RUNNING globally."""
        repo_a = await _seed_repo(
            session_factory, name="repo-a", gid=9101, install_id=91001
        )
        repo_b = await _seed_repo(
            session_factory, name="repo-b", gid=9102, install_id=91002
        )
        await _seed_job(session_factory, repo_a, 1)
        await _seed_job(session_factory, repo_b, 27)

        first = await _claim(session_factory)
        assert first is not None
        assert await _running_count(session_factory) == 1

        second = await _claim(session_factory)
        assert second is None
        assert await _running_count(session_factory) == 1

    async def test_one_repo_multiple_jobs_only_one_running(self, session_factory):
        """2. One repository with multiple jobs → only ONE RUNNING."""
        repo = await _seed_repo(
            session_factory, name="solo", gid=9111, install_id=91101
        )
        await _seed_job(session_factory, repo, 1)
        await _seed_job(session_factory, repo, 2)
        await _seed_job(session_factory, repo, 3)

        first = await _claim(session_factory)
        assert first is not None
        assert await _running_count(session_factory) == 1

        second = await _claim(session_factory)
        assert second is None
        assert await _running_count(session_factory) == 1

    async def test_fairness_other_repo_gets_next_turn(self, session_factory):
        """3. After A1 completes, Repo B runs next; then A2."""
        repo_a = await _seed_repo(
            session_factory, name="busy-a", gid=9121, install_id=91201
        )
        repo_b = await _seed_repo(
            session_factory, name="quiet-b", gid=9122, install_id=91202
        )
        base = datetime.now(UTC) - timedelta(minutes=30)
        await _seed_job(
            session_factory, repo_a, 1, created_at=base + timedelta(seconds=1)
        )
        await _seed_job(
            session_factory, repo_a, 2, created_at=base + timedelta(seconds=2)
        )
        await _seed_job(
            session_factory, repo_a, 3, created_at=base + timedelta(seconds=3)
        )
        await _seed_job(
            session_factory, repo_b, 27, created_at=base + timedelta(seconds=4)
        )

        first = await _claim(session_factory)
        assert first is not None
        assert first[1] == repo_a.id
        assert await _running_count(session_factory) == 1

        # A1 still running → B cannot claim.
        assert await _claim(session_factory) is None

        await _set_status(
            session_factory,
            first[0],
            JobStatus.COMPLETED,
            completed_at=datetime.now(UTC),
        )
        assert await _running_count(session_factory) == 0

        # Fairness: B has no completed jobs (epoch), A just completed → B wins.
        second = await _claim(session_factory)
        assert second is not None
        assert second[1] == repo_b.id, "Repo B must get the next turn"
        assert second[2] == 27

        await _set_status(
            session_factory,
            second[0],
            JobStatus.COMPLETED,
            completed_at=datetime.now(UTC),
        )

        third = await _claim(session_factory)
        assert third is not None
        assert third[1] == repo_a.id, "Then back to Repo A"
        assert third[2] == 2, "Per-repo FIFO: A2 before A3"

    async def test_concurrent_claims_only_one_succeeds(self, session_factory):
        """4. Two workers claiming simultaneously → only one succeeds."""
        repo_a = await _seed_repo(
            session_factory, name="race-a", gid=9131, install_id=91301
        )
        repo_b = await _seed_repo(
            session_factory, name="race-b", gid=9132, install_id=91302
        )
        await _seed_job(session_factory, repo_a, 1)
        await _seed_job(session_factory, repo_b, 1)

        results = await asyncio.gather(
            _claim_locked(session_factory),
            _claim_locked(session_factory),
        )
        successes = [r for r in results if r is not None]
        assert len(successes) == 1, "exactly one concurrent claim may succeed"
        assert await _running_count(session_factory) == 1

    async def test_running_job_blocks_additional_claims(self, session_factory):
        """5. A running job blocks claims from any other repository."""
        repo_a = await _seed_repo(
            session_factory, name="holder", gid=9141, install_id=91401
        )
        repo_b = await _seed_repo(
            session_factory, name="blocked", gid=9142, install_id=91402
        )
        await _seed_job(session_factory, repo_a, 1, status=JobStatus.RUNNING)
        await _seed_job(session_factory, repo_b, 9)

        assert await _claim(session_factory) is None
        assert await _running_count(session_factory) == 1

    async def test_completed_releases_global_slot(self, session_factory):
        """6. Completed job releases the global slot."""
        repo = await _seed_repo(
            session_factory, name="done", gid=9151, install_id=91501
        )
        job = await _seed_job(session_factory, repo, 1, status=JobStatus.RUNNING)
        await _seed_job(session_factory, repo, 2)

        assert await _claim(session_factory) is None
        await _set_status(
            session_factory, job.id, JobStatus.COMPLETED, completed_at=datetime.now(UTC)
        )
        claimed = await _claim(session_factory)
        assert claimed is not None
        assert claimed[0] != job.id
        assert await _running_count(session_factory) == 1

    async def test_failed_releases_global_slot(self, session_factory):
        """7. Failed job releases the global slot."""
        repo = await _seed_repo(
            session_factory, name="fail", gid=9161, install_id=91601
        )
        job = await _seed_job(session_factory, repo, 1, status=JobStatus.RUNNING)
        await _seed_job(session_factory, repo, 2)

        await _set_status(session_factory, job.id, JobStatus.FAILED)
        assert await _running_count(session_factory) == 0
        claimed = await _claim(session_factory)
        assert claimed is not None
        assert claimed[0] != job.id

    async def test_cancelled_releases_global_slot(self, session_factory):
        """8. Cancelled job releases the global slot."""
        repo = await _seed_repo(
            session_factory, name="cancel", gid=9171, install_id=91701
        )
        job = await _seed_job(session_factory, repo, 1, status=JobStatus.RUNNING)
        await _seed_job(session_factory, repo, 2)

        await _set_status(session_factory, job.id, JobStatus.CANCELLED)
        assert await _running_count(session_factory) == 0
        claimed = await _claim(session_factory)
        assert claimed is not None
        assert claimed[0] != job.id

    async def test_stale_recovery_no_duplicate_execution(self, session_factory):
        """9. Stale RUNNING job is re-queued without creating a second job."""
        from app.queue import worker as worker_mod

        repo = await _seed_repo(
            session_factory, name="stale", gid=9181, install_id=91801
        )
        stale = await _seed_job(session_factory, repo, 1, status=JobStatus.RUNNING)
        await _seed_job(session_factory, repo, 2)

        # Nothing else can run while the (stale) job is RUNNING.
        assert await _claim(session_factory) is None

        # Age the heartbeat past the timeout, then recover (startup path).
        async with session_factory() as db:
            job = await db.get(ReviewJob, stale.id)
            job.updated_at = datetime.now(UTC) - timedelta(seconds=300)
            db.add(job)
            await db.commit()

        await worker_mod.recover_orphaned_jobs(
            queue_timeout_minutes=30, heartbeat_timeout_seconds=120
        )

        async with session_factory() as db:
            jobs = (await db.execute(select(ReviewJob))).scalars().all()
            # No duplicate ReviewJob rows.
            assert len(jobs) == 2
            statuses = {j.id: j.status for j in jobs}
            assert statuses[stale.id] == JobStatus.QUEUED

        claimed = await _claim(session_factory)
        assert claimed is not None
        # Re-claims the SAME job id — no duplicate execution identity.
        assert claimed[0] == stale.id
        assert await _running_count(session_factory) == 1

    async def test_backend_restart_recovery_allows_next_claim(
        self, session_factory
    ):
        """10. After restart-style recovery, the next queued job may run."""
        from app.queue import worker as worker_mod

        repo = await _seed_repo(
            session_factory, name="reboot", gid=9191, install_id=91901
        )
        orphan = await _seed_job(session_factory, repo, 1, status=JobStatus.RUNNING)
        await _seed_job(session_factory, repo, 2)

        async with session_factory() as db:
            job = await db.get(ReviewJob, orphan.id)
            job.updated_at = datetime.now(UTC) - timedelta(seconds=300)
            db.add(job)
            await db.commit()

        # Fresh worker start: recover_orphaned_jobs() then claim.
        # (monkeypatch on the fixture already cleared the anchors; set the
        # started-at anchor here to model a just-booted process.)
        worker_mod._worker_started_at = datetime.now(UTC)
        worker_mod._last_claim_at = None
        await worker_mod.recover_orphaned_jobs(
            queue_timeout_minutes=30, heartbeat_timeout_seconds=120
        )

        assert await _running_count(session_factory) == 0
        claimed = await _claim(session_factory)
        assert claimed is not None
        assert claimed[0] == orphan.id

    async def test_per_repo_fifo_preserved(self, session_factory):
        """11. Within a repo, oldest queued job is always claimed first."""
        repo = await _seed_repo(
            session_factory, name="fifo", gid=9201, install_id=92001
        )
        base = datetime.now(UTC) - timedelta(minutes=10)
        j1 = await _seed_job(
            session_factory, repo, 1, created_at=base + timedelta(seconds=1)
        )
        await _seed_job(
            session_factory, repo, 2, created_at=base + timedelta(seconds=2)
        )
        await _seed_job(
            session_factory, repo, 3, created_at=base + timedelta(seconds=3)
        )

        c1 = await _claim(session_factory)
        assert c1[0] == j1.id
        await _set_status(
            session_factory, j1.id, JobStatus.COMPLETED, completed_at=datetime.now(UTC)
        )

        c2 = await _claim(session_factory)
        async with session_factory() as db:
            job2 = await db.get(ReviewJob, c2[0])
            assert job2.pr_number == 2


class TestGlobalClaimShapeAndTopology:
    def test_worker_source_has_global_running_guard(self):
        source = WORKER_PATH.read_text(encoding="utf-8")
        assert "REVIEW_CLAIM_ADVISORY_LOCK_KEY" in source
        assert "WHERE gr.status = 'running'" in source
        assert "async def claim_next_job" in source
        assert "async def claim_next_job_with_factory" in source
        assert "REVIEW_CLAIM_ADVISORY_LOCK_KEY" in source
        # Claim must not reuse the sync full-pass lock key name.
        assert "FULL_PASS_ADVISORY_LOCK_KEY =" not in source
        # Per-repo single-flight retained.
        assert "pg_try_advisory_xact_lock(hashtext(j.repo_id::text))" in source
        # Fair scheduler retained.
        assert "ORDER BY last_completed ASC" in source
        assert "GROUP BY j.repo_id" in source
        assert "FOR UPDATE SKIP LOCKED" in source

    def test_dispatcher_webhook_shape_untouched(self):
        """12. Webhook idempotency / lifecycle / supersede still present."""
        source = DISPATCHER_PATH.read_text(encoding="utf-8")
        assert "on_conflict_do_nothing" in source
        assert 'index_elements=["delivery_id", "head_sha"]' in source
        assert "def supersede_jobs" in source
        assert "def enqueue_lifecycle_job" in source
        assert 'status.in_([JobStatus.QUEUED, JobStatus.RUNNING])' in source

    def test_run_bat_starts_single_embedded_worker(self):
        run_bat = ROOT / "run.bat"
        assert run_bat.exists()
        text = run_bat.read_text(encoding="utf-8")
        # No standalone worker process.
        assert "python -m app.queue.worker" not in text
        assert "app.queue.worker" not in text
        # Backend still starts (embedded worker via lifespan).
        assert "uvicorn app.main:app" in text

    def test_main_embedded_worker_is_the_single_source(self):
        main_src = (WORKER_PATH.parent.parent / "main.py").read_text(
            encoding="utf-8"
        )
        assert "run_worker(standalone=False)" in main_src
        assert "asyncio.create_task(run_worker" in main_src

    def test_dev_compose_has_no_duplicate_worker_service(self):
        compose = ROOT / "docker-compose.yml"
        text = compose.read_text(encoding="utf-8")
        assert "python -m app.queue" not in text
        # No top-level worker service key.
        assert "\n  worker:" not in text
        assert "uvicorn app.main:app" in text

    def test_prod_compose_single_process_single_worker(self):
        compose = ROOT / "docker-compose.prod.yml"
        text = compose.read_text(encoding="utf-8")
        assert "--workers 1" in text
        assert "--workers 2" not in text
        assert "python -m app.queue" not in text
        assert "\n  worker:" not in text

    def test_start_sh_single_uvicorn_worker(self):
        start_sh = WORKER_PATH.parents[2] / "start.sh"
        text = start_sh.read_text(encoding="utf-8")
        assert "--workers 1" in text
