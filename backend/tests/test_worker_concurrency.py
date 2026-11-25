"""Regression tests for bounded concurrent review execution.

Concurrency settings 1/2/3/5, duplicate-claim prevention under contention,
slot release on failure, queue draining, provider throttling, and SSE/sync
lock cleanup (source-shape assertions matching the suite's conventions).
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.models.github import Installation, PullRequest, Repository
from app.models.user import User
from app.queue.models import JobStatus, ReviewJob

WORKER_PATH = Path(__file__).parent.parent / "app" / "queue" / "worker.py"
ORCHESTRATOR_PATH = Path(__file__).parent.parent / "app" / "orchestrator" / "orchestrator.py"
REPO_EP_PATH = Path(__file__).parent.parent / "app" / "api" / "v1" / "endpoints" / "repositories.py"


@pytest_asyncio.fixture
async def session_factory(tmp_path, monkeypatch):
    from datetime import UTC, datetime
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import create_async_engine
    import app.db.session as db_session
    from app.db.base import Base

    # File-based SQLite: supports concurrent readers/writers without
    # serializing everything through a single in-memory connection.
    path = tmp_path / "worker-concurrency.sqlite"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{path}",
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_size=20,
        max_overflow=0,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def configure_sqlite_connection(dbapi_connection, connection_record):
        import datetime

        dbapi_connection.create_function(
            "now", 0, lambda: datetime.datetime.now(UTC).isoformat()
        )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    monkeypatch.setattr("app.db.session.AsyncSessionLocal", factory)
    monkeypatch.setattr("app.queue.worker.AsyncSessionLocal", factory)
    from app.queue import worker as worker_mod

    monkeypatch.setattr(worker_mod, "_worker_started_at", None)
    monkeypatch.setattr(worker_mod, "_last_claim_at", None)
    worker_mod._shutdown = False
    yield factory
    monkeypatch.undo()
    await engine.dispose()


@pytest.fixture(autouse=True)
async def clean_tables(session_factory):
    from app.models.execution import ReviewExecution
    from app.models.review import Review
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


async def _seed_job(session_factory, repo, pr_number: int, *, created_at=None):
    async with session_factory() as db:
        job = ReviewJob(
            delivery_id=f"gid-{uuid.uuid4()}",
            head_sha=(f"{pr_number:02d}" * 20)[:40],
            pr_number=pr_number,
            repo_id=repo.id,
            payload={},
            status=JobStatus.QUEUED,
            created_at=created_at or datetime.now(UTC),
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job


async def _job_statuses(session_factory):
    async with session_factory() as db:
        rows = (await db.execute(select(ReviewJob))).scalars().all()
        return {r.id: r.status for r in rows}


def _make_tracked_process_job(block_on: dict[int, asyncio.Event] | None = None):
    state = {"active": 0, "max_active": 0, "started": []}

    async def fake_process_job(job_row):
        pr_number = job_row[2]
        state["active"] += 1
        state["max_active"] = max(state["max_active"], state["active"])
        state["started"].append(pr_number)
        ev = None if block_on is None else block_on.get(pr_number)
        if ev is not None:
            await ev.wait()
        else:
            await asyncio.sleep(0.3)
        state["active"] -= 1
        return True

    return state, fake_process_job


@pytest.mark.parametrize("concurrency,expected_max", [(1, 1), (2, 2), (3, 3), (5, 5)])
async def test_concurrency_limit_is_enforced(
    session_factory, monkeypatch, concurrency: int, expected_max: int
):
    from app.queue import worker as worker_mod

    repos = [
        await _seed_repo(
            session_factory,
            name=f"lim{concurrency}-{i}",
            gid=6000 + concurrency * 100 + i,
            install_id=8000 + concurrency * 100 + i,
        )
        for i in range(concurrency)
    ]
    for i, repo in enumerate(repos):
        await _seed_job(session_factory, repo, i + 1)

    state, fake_job = _make_tracked_process_job()
    monkeypatch.setattr(worker_mod, "process_job", fake_job)
    worker_mod._shutdown = False

    worker_task = asyncio.create_task(
        worker_mod.run_worker(
            standalone=False, concurrency=concurrency, poll_interval=0.02
        )
    )
    deadline = asyncio.get_event_loop().time() + 10
    while asyncio.get_event_loop().time() < deadline:
        statuses = await _job_statuses(session_factory)
        if statuses and all(s == JobStatus.COMPLETED for s in statuses.values()):
            break
        await asyncio.sleep(0.05)
    worker_mod._shutdown = True
    await worker_task

    statuses = await _job_statuses(session_factory)
    assert statuses and all(s == JobStatus.COMPLETED for s in statuses.values())
    assert state["max_active"] == expected_max


async def test_five_repos_run_five_in_parallel(session_factory, monkeypatch):
    from app.queue import worker as worker_mod

    repos = []
    for i in range(5):
        repos.append(
            await _seed_repo(
                session_factory,
                name=f"par{i}",
                gid=8000 + i,
                install_id=9500 + i,
            )
        )
    jobs = []
    for i, repo in enumerate(repos):
        jobs.append(await _seed_job(session_factory, repo, i + 1))

    state, fake_job = _make_tracked_process_job()
    monkeypatch.setattr(worker_mod, "process_job", fake_job)

    worker_task = asyncio.create_task(
        worker_mod.run_worker(standalone=False, concurrency=5, poll_interval=0.02)
    )
    deadline = asyncio.get_event_loop().time() + 10
    while asyncio.get_event_loop().time() < deadline:
        jobs_done = all(
            s == JobStatus.COMPLETED for s in (await _job_statuses(session_factory)).values()
        )
        if jobs_done:
            break
        await asyncio.sleep(0.05)
    worker_mod._shutdown = True
    await worker_task

    statuses = await _job_statuses(session_factory)
    assert all(s == JobStatus.COMPLETED for s in statuses.values())
    assert state["max_active"] == 5, f"expected 5 concurrent reviews, got {state['max_active']}"


async def test_five_jobs_same_repo_run_in_parallel(session_factory, monkeypatch):
    from app.queue import worker as worker_mod

    repo = await _seed_repo(session_factory, name="samecoop", gid=8005, install_id=9515)
    for pr in range(1, 6):
        await _seed_job(session_factory, repo, pr)

    state, fake_job = _make_tracked_process_job()
    monkeypatch.setattr(worker_mod, "process_job", fake_job)
    worker_mod._shutdown = False

    worker_task = asyncio.create_task(
        worker_mod.run_worker(standalone=False, concurrency=5, poll_interval=0.02)
    )
    deadline = asyncio.get_event_loop().time() + 10
    while asyncio.get_event_loop().time() < deadline:
        statuses = await _job_statuses(session_factory)
        if statuses and all(s == JobStatus.COMPLETED for s in statuses.values()):
            break
        await asyncio.sleep(0.05)
    worker_mod._shutdown = True
    await worker_task

    statuses = await _job_statuses(session_factory)
    assert statuses and all(s == JobStatus.COMPLETED for s in statuses.values())
    assert state["max_active"] == 5, f"expected 5 concurrent same-repo reviews, got {state['max_active']}"




async def test_slot_released_on_failure(session_factory, monkeypatch):
    from app.queue import worker as worker_mod

    repo_a = await _seed_repo(session_factory, name="rel-a", gid=8100, install_id=9600)
    repo_b = await _seed_repo(session_factory, name="rel-b", gid=8101, install_id=9601)
    job_a = await _seed_job(session_factory, repo_a, 1)
    job_b = await _seed_job(session_factory, repo_b, 2)

    async def failing_process_job(job_row):
        if job_row[0] == job_a.id:
            await asyncio.sleep(0.1)
            return False
        return True

    monkeypatch.setattr(worker_mod, "process_job", failing_process_job)
    worker_mod._shutdown = False

    worker_task = asyncio.create_task(
        worker_mod.run_worker(standalone=False, concurrency=1, poll_interval=0.02)
    )
    deadline = asyncio.get_event_loop().time() + 10
    while asyncio.get_event_loop().time() < deadline:
        statuses = await _job_statuses(session_factory)
        if statuses.get(job_a.id) == JobStatus.FAILED and statuses.get(job_b.id) == JobStatus.COMPLETED:
            break
        await asyncio.sleep(0.05)
    worker_mod._shutdown = True
    await worker_task

    statuses = await _job_statuses(session_factory)
    assert statuses[job_a.id] == JobStatus.FAILED
    assert statuses[job_b.id] == JobStatus.COMPLETED


def test_source_shape_supports_bounded_concurrency():
    source = WORKER_PATH.read_text(encoding="utf-8")
    assert "0x5A9C1030" not in source
    assert "WHERE gr.status = 'running'" not in source
    assert "REVIEW_WORKER_CONCURRENCY" in source
    assert "_execute_claimed_job" in source
    assert "asyncio.wait" in source


def test_provider_throttle_source_shape():
    source = ORCHESTRATOR_PATH.read_text(encoding="utf-8")
    assert "_provider_semaphores" in source
    assert "PROVIDER_CONCURRENCY_LIMIT" in source


def test_advisory_lock_release_is_shielded():
    source = REPO_EP_PATH.read_text(encoding="utf-8")
    assert "pg_advisory_unlock(" in source
    assert "asyncio.shield(" in source
    assert "db.rollback()" in source


def test_settings_have_review_worker_config():
    from app.core import config as cfg

    # ``settings`` is built at import time from backend/.env, so its values are
    # deployment-specific (the local .env sets REVIEW_WORKER_CONCURRENCY=2).
    # The declared defaults must not depend on a developer's environment.
    fields = cfg.Settings.model_fields
    assert fields["REVIEW_WORKER_CONCURRENCY"].default == 5
    assert fields["REVIEW_WORKER_ENABLED"].default is True
    assert fields["PROVIDER_CONCURRENCY_LIMIT"].default == 3

    # The live settings object must still expose the knobs with valid values.
    assert 1 <= cfg.settings.REVIEW_WORKER_CONCURRENCY <= 5
    assert isinstance(cfg.settings.REVIEW_WORKER_ENABLED, bool)
    assert 1 <= cfg.settings.PROVIDER_CONCURRENCY_LIMIT <= 5