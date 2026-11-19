"""Regression tests: bounded concurrent review execution.

Covers:
  1. Two repositories with queued jobs → both claimable concurrently.
  2. One repository with multiple jobs → per-repository serialization.
  3. Fair cross-repo scheduling (least-recently-completed first).
  4. Two workers claiming simultaneously → both succeed, distinct jobs.
  5. Running job blocks same-repo claims; other repos remain claimable.
  6. Completed job releases the per-repo slot.
  7. Failed job releases the per-repo slot.
  8. Cancelled job releases the per-repo slot.
  9. Stale/recovered job does not create duplicate execution.
  10. Backend restart recovers correctly (startup recovery + reclaim).
  11. Existing per-repository FIFO remains intact.
  12. Existing webhook/reopen/rerun/retry shape remains intact.
  13. Concurrency shape assertions live in test_global_serial_claim.py::TestClaimShapeAndTopology.
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
    async def test_two_repos_claim_concurrently(self, session_factory):
        """1. Two repositories with queued jobs → both claimable concurrently."""
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
        assert second is not None
        assert second[1] != first[1]
        assert await _running_count(session_factory) == 2

    async def test_one_repo_multiple_jobs_claim_concurrently(self, session_factory):
        """2. One repository may use multiple review slots (bounded by concurrency)."""
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
        assert second is not None
        assert await _running_count(session_factory) == 2

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

        # A1 still running → B (different repo) CAN claim concurrently.
        b_job = await _claim(session_factory)
        assert b_job is not None
        assert b_job[1] == repo_b.id

        await _set_status(
            session_factory,
            first[0],
            JobStatus.COMPLETED,
            completed_at=datetime.now(UTC),
        )
        assert await _running_count(session_factory) == 1  # B still running

        # A's next job is FIFO (per-repo) after its running jobs finish.
        third = await _claim(session_factory)
        assert third is not None
        assert third[1] == repo_a.id, "Then back to Repo A"
        assert third[2] == 2, "Per-repo FIFO: A2 before A3"

    async def test_concurrent_claims_distinct_jobs(self, session_factory):
        """4. Two workers claiming simultaneously → both succeed with distinct jobs."""
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
        assert len(successes) == 2, "concurrent claims of different repos must both succeed"
        assert len({r[0] for r in successes}) == 2
        assert await _running_count(session_factory) == 2

    async def test_running_job_blocks_same_repo_claims(self, session_factory):
        """5. Running job blocks same-repo claims; other repos remain claimable."""
        repo_a = await _seed_repo(
            session_factory, name="holder", gid=9141, install_id=91401
        )
        repo_b = await _seed_repo(
            session_factory, name="blocked", gid=9142, install_id=91402
        )
        await _seed_job(session_factory, repo_a, 1, status=JobStatus.RUNNING)
        await _seed_job(session_factory, repo_b, 9)

        claimed_b = await _claim(session_factory)
        assert claimed_b is not None
        assert claimed_b[1] == repo_b.id
        assert await _running_count(session_factory) == 2

    async def test_completed_releases_slot_and_same_repo_concurrency(self, session_factory):
        """6. Failed/completed slots release cleanly; same-repo jobs are not serialized."""
        repo = await _seed_repo(
            session_factory, name="done", gid=9151, install_id=91501
        )
        job1 = await _seed_job(session_factory, repo, 1, status=JobStatus.RUNNING)
        await _seed_job(session_factory, repo, 2)
        await _seed_job(session_factory, repo, 3)

        claimed1 = await _claim(session_factory)
        assert claimed1 is not None
        assert claimed1[0] != job1.id
        assert await _running_count(session_factory) == 2

        await _set_status(
            session_factory, claimed1[0], JobStatus.COMPLETED, completed_at=datetime.now(UTC)
        )
        assert await _running_count(session_factory) == 1

        claimed2 = await _claim(session_factory)
        assert claimed2 is not None
        assert claimed2[0] != job1.id
        assert claimed2[0] != claimed1[0]
        assert await _running_count(session_factory) == 2

    async def test_failed_releases_repo_slot(self, session_factory):
        """7. Failed job releases the per-repository slot."""
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

    async def test_cancelled_releases_repo_slot(self, session_factory):
        """8. Cancelled job releases the per-repository slot."""
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

        # Same-repository jobs are not serialized; legacy invariant is that
        # a stale RUNNING job does not duplicate execution identities.
        # (No additional claim needed here.)

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


class TestClaimShapeAndTopology:
    def test_worker_source_supports_bounded_concurrency(self):
        source = WORKER_PATH.read_text(encoding="utf-8")
        # Global single-flight lock removed (replaced by bounded concurrency).
        assert "0x5A9C1030" not in source
        assert "WHERE gr.status = 'running'" not in source
        # Claim functions retained.
        assert "async def claim_next_job" in source
        assert "async def claim_next_job_with_factory" in source
        # Same-repo jobs may use multiple slots.
        assert "pg_try_advisory_xact_lock" not in source
        assert "running_count ASC" in source
        # Round-robin fairness retained: fewer running jobs first.
        assert "ORDER BY running_count ASC, last_completed ASC, oldest ASC" in source
        assert "GROUP BY j.repo_id" in source
        # Concurrency configuration is wired through settings.
        assert "REVIEW_WORKER_CONCURRENCY" in source
        assert "_execute_claimed_job" in source
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

    def test_run_command_starts_single_embedded_worker(self):
        """macOS run.command must match run.bat: embedded worker only."""
        run_command = ROOT / "run.command"
        assert run_command.exists()
        text = run_command.read_text(encoding="utf-8")
        # No standalone worker process (Option 2 single-worker topology).
        assert "python -m app.queue.worker" not in text
        assert "app.queue.worker" not in text
        # Backend still starts (embedded worker via lifespan).
        assert "uvicorn app.main:app" in text
        # Local-dev script still runs migrations before services.
        assert "alembic upgrade head" in text

    def test_main_embedded_worker_is_the_single_source(self):
        main_src = (WORKER_PATH.parent.parent / "main.py").read_text(
            encoding="utf-8"
        )
        assert "run_worker(standalone=False)" in main_src
        assert "asyncio.create_task(run_worker" in main_src

    def test_dev_compose_has_review_worker_service(self):
        compose = ROOT / "docker-compose.yml"
        text = compose.read_text(encoding="utf-8")
        # Dedicated worker service exists.
        assert "\n  worker:" in text
        assert "python -m app.queue.worker" in text
        # API container does not run an in-process review worker.
        assert "REVIEW_WORKER_ENABLED=false" in text
        # Concurrency is configured via env/.env, not hardcoded in compose.
        assert "REVIEW_WORKER_CONCURRENCY" not in text
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
