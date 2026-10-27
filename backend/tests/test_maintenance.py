"""Phase 5 suite: global maintenance mode (§12, B24/B25/B26/B31).

Covers the service TTL/write-through semantics, the enforcement middleware
(503 + exemptions + no cookie minting), the admin GET/PUT surface with
optimistic concurrency, audit rows, the public `/platform/status` payload
and the worker claim gate (jobs persist and resume, in-flight jobs are
never touched).
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.middleware.maintenance import is_maintenance_exempt
from app.middleware.rate_limit import limiter
from app.models.audit import AuditLog
from app.models.execution import ReviewExecution
from app.models.github import Installation, PullRequest, Repository
from app.models.platform import FeatureFlag, PlatformSetting
from app.models.provider import ProviderRegistry
from app.models.review import Review
from app.models.sync_run import SyncRun
from app.models.user import User
from app.queue.models import JobStatus, ReviewJob
from app.queue.worker import claim_next_job_with_factory
from app.services.platform_settings import platform_settings_service


@pytest.fixture(autouse=True)
def _reset_limiter():
    """Keep the per-IP limiter from bleeding across tests (as elsewhere)."""
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
async def worker_env(test_engine, monkeypatch):
    """Committed-session factory over the test engine (claim-path tests)."""
    from app.queue import worker as worker_mod

    factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    monkeypatch.setattr("app.db.session.AsyncSessionLocal", factory)
    monkeypatch.setattr("app.queue.worker.AsyncSessionLocal", factory)
    monkeypatch.setattr(worker_mod, "_worker_started_at", None)
    monkeypatch.setattr(worker_mod, "_last_claim_at", None)
    yield factory
    async with factory() as db:
        for model in (
            ReviewExecution,
            Review,
            PullRequest,
            Repository,
            Installation,
            ReviewJob,
            SyncRun,
            User,
            PlatformSetting,
        ):
            await db.execute(model.__table__.delete())
        await db.commit()


async def _seed_maintenance(db, *, enabled: bool, **fields):
    state, _prior, conflict = await platform_settings_service.set_maintenance(
        db, {"enabled": enabled, **fields}
    )
    assert conflict is None
    await db.commit()
    return state


async def _seed_repo(factory, *, name: str, gid: int, install_id: int):
    async with factory() as db:
        user = User(
            id=uuid.uuid4(),
            name="M",
            email=f"{name}@example.com",
            role="user",
            is_verified=True,
        )
        db.add(user)
        inst = Installation(
            id=uuid.uuid4(),
            installation_id=install_id,
            account_id=1,
            account_login="maintenanceowner",
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
            full_name=f"maintenanceowner/{name}",
            is_private=False,
            installation_id=inst.id,
            reviews_enabled=True,
        )
        db.add(repo)
        await db.commit()
        await db.refresh(repo)
        return repo


async def _seed_job(factory, repo, pr_number: int, *, status=JobStatus.QUEUED):
    async with factory() as db:
        job = ReviewJob(
            delivery_id=f"gid-{uuid.uuid4()}",
            head_sha=(f"{pr_number:02d}" * 20)[:40],
            pr_number=pr_number,
            repo_id=repo.id,
            payload={},
            status=status,
            created_at=datetime.now(UTC),
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job


async def _job_status(factory, job_id):
    async with factory() as db:
        row = await db.get(ReviewJob, job_id)
        return row.status, row.completed_at


async def _job_count(factory) -> int:
    async with factory() as db:
        return (
            await db.execute(select(func.count()).select_from(ReviewJob))
        ).scalar() or 0


# ---------------------------------------------------------------------------
# Service semantics (§12.1)
# ---------------------------------------------------------------------------


async def test_service_defaults_when_no_row(test_db):
    state = await platform_settings_service.get_maintenance(test_db)
    assert state["enabled"] is False
    assert state["version"] == 0


async def test_service_write_through_and_versioning(test_db):
    first, prior, conflict = await platform_settings_service.set_maintenance(
        test_db, {"enabled": True, "reason": "db swap"}
    )
    assert conflict is None
    assert first["version"] == 1
    assert prior["version"] == 0

    second, prior2, conflict2 = await platform_settings_service.set_maintenance(
        test_db, {"message": "Back soon"}
    )
    assert conflict2 is None
    assert second["version"] == 2
    assert second["message"] == "Back soon"
    assert prior2["enabled"] is True

    # Cache was primed by the write-through (no DB session provided here).
    cached = await platform_settings_service.get_maintenance()
    assert cached["enabled"] is True
    assert cached["version"] == 2


async def test_service_conflict_leaves_state_unchanged(test_db):
    await platform_settings_service.set_maintenance(test_db, {"enabled": True})

    stale, _prior, conflict = await platform_settings_service.set_maintenance(
        test_db, {"enabled": False}, expected_version=0
    )
    assert conflict == 1
    assert stale["enabled"] is True

    fresh = await platform_settings_service.get_maintenance(test_db, force=True)
    assert fresh["enabled"] is True
    assert fresh["version"] == 1


async def test_service_fail_open_when_db_unreachable():
    class _BrokenFactory:
        def __call__(self):
            raise RuntimeError("db down")

    original = platform_settings_service.db_factory
    platform_settings_service.db_factory = _BrokenFactory()
    try:
        state = await platform_settings_service.get_maintenance()
        assert state["enabled"] is False
    finally:
        platform_settings_service.db_factory = original


# ---------------------------------------------------------------------------
# B24 — enforcement middleware (§12.3)
# ---------------------------------------------------------------------------


def test_exempt_matcher_is_segment_aware():
    assert is_maintenance_exempt("/readyz")
    assert is_maintenance_exempt("/livez")
    assert is_maintenance_exempt("/api/v1/health")
    assert is_maintenance_exempt("/api/v1/platform/status")
    assert is_maintenance_exempt("/api/v1/webhooks/github")
    assert is_maintenance_exempt("/api/v1/admin/maintenance")
    assert not is_maintenance_exempt("/api/v1/platform-analytics/overview")
    assert not is_maintenance_exempt("/api/v1/providers")
    assert not is_maintenance_exempt("/api/v1/adminx")


async def test_b24_blocks_user_reads_with_503_no_cookie(client, test_db):
    await _seed_maintenance(
        test_db, enabled=True, title="Upgrades", message="Back soon"
    )
    response = client.get("/api/v1/providers")
    assert response.status_code == 503
    assert response.json() == {"code": "maintenance"}
    assert "set-cookie" not in response.headers


async def test_b24_blocks_login_before_any_cookie(anon_client, test_db):
    await _seed_maintenance(test_db, enabled=True)
    response = anon_client.post(
        "/api/v1/auth/login",
        json={"email": "someone@example.com", "password": "hunter2"},
    )
    assert response.status_code == 503
    assert response.json() == {"code": "maintenance"}
    assert "set-cookie" not in response.headers


async def test_b24_exempt_routes_stay_up(anon_client, admin_client, test_db):
    await _seed_maintenance(test_db, enabled=True)

    assert anon_client.get("/api/v1/health").status_code == 200

    status = anon_client.get("/api/v1/platform/status")
    assert status.status_code == 200
    assert status.json()["maintenance"]["enabled"] is True

    assert admin_client.get("/api/v1/admin/auth/session").status_code == 200

    webhook = anon_client.post(
        "/api/v1/webhooks/github",
        content=b"{}",
        headers={"X-GitHub-Event": "ping"},
    )
    assert webhook.status_code != 503


async def test_b24_disable_restores_traffic(client, test_db):
    await _seed_maintenance(test_db, enabled=True)
    assert client.get("/api/v1/providers").status_code == 503

    await _seed_maintenance(test_db, enabled=False)
    response = client.get("/api/v1/providers")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# B25 / B31 — admin surface, recovery, audit (§12.2, §18)
# ---------------------------------------------------------------------------


async def test_admin_get_exposes_internal_fields(admin_client, test_db):
    await _seed_maintenance(
        test_db,
        enabled=True,
        title="Upgrade",
        message="Back soon",
        expected_return_at="2026-01-01T10:00:00+00:00",
        reason="db migration",
    )
    response = admin_client.get("/api/v1/admin/maintenance")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["reason"] == "db migration"
    assert body["changed_by"] == "system"
    assert body["version"] == 1


async def test_b25_admin_disable_recovers_without_redeploy(
    admin_client, test_db
):
    await _seed_maintenance(test_db, enabled=True)
    assert admin_client.get("/api/v1/providers").status_code == 503

    response = admin_client.put(
        "/api/v1/admin/maintenance",
        json={"enabled": False, "version": 1},
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is False

    # Gate reopened: the route now answers with its normal auth outcome.
    assert admin_client.get("/api/v1/providers").status_code == 401

    rows = (
        (
            await test_db.execute(
                select(AuditLog).where(
                    AuditLog.action == "admin.maintenance_disabled",
                    AuditLog.entity_id == "maintenance",
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows, "disable must be audited"
    assert rows[-1].details.get("outcome") == "success"


async def test_b31_admin_enable_blocks_users_but_console_lives(
    admin_client, test_db
):
    response = admin_client.put(
        "/api/v1/admin/maintenance",
        json={
            "enabled": True,
            "title": "Upgrades",
            "message": "Back by 18:00",
            "reason": "invoice",
        },
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is True
    assert response.json()["version"] == 1

    # User traffic blocked, admin console fully usable (S9).
    assert admin_client.get("/api/v1/providers").status_code == 503
    assert admin_client.get("/api/v1/admin/overview").status_code == 200
    assert admin_client.get("/api/v1/admin/maintenance").status_code == 200

    rows = (
        (
            await test_db.execute(
                select(AuditLog).where(
                    AuditLog.action == "admin.maintenance_enabled",
                    AuditLog.entity_id == "maintenance",
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows, "enable must be audited"

    # Cleanup so the shared engine does not stay blocked for other suites.
    cleanup = admin_client.put(
        "/api/v1/admin/maintenance", json={"enabled": False}
    )
    assert cleanup.status_code == 200


async def test_maintenance_message_update_is_audited(admin_client, test_db):
    await _seed_maintenance(test_db, enabled=True)
    response = admin_client.put(
        "/api/v1/admin/maintenance",
        json={"message": "New ETA text", "version": 1},
    )
    assert response.status_code == 200
    assert response.json()["message"] == "New ETA text"

    rows = (
        (
            await test_db.execute(
                select(AuditLog).where(
                    AuditLog.action == "admin.maintenance_message_updated",
                    AuditLog.entity_id == "maintenance",
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows, "message update must be audited"


async def test_b25_put_conflict_409(admin_client, test_db):
    await _seed_maintenance(test_db, enabled=True)
    response = admin_client.put(
        "/api/v1/admin/maintenance",
        json={"enabled": False, "version": 0},
    )
    assert response.status_code == 409

    still = await platform_settings_service.get_maintenance(test_db, force=True)
    assert still["enabled"] is True
    assert still["version"] == 1


async def test_put_maintenance_cross_origin_403(admin_client, test_db):
    """S-suite: OriginCheckMiddleware still guards admin mutations (§12.3)."""
    await _seed_maintenance(test_db, enabled=True)
    response = admin_client.put(
        "/api/v1/admin/maintenance",
        json={"enabled": False},
        headers={"Origin": "https://evil.example.org"},
    )
    assert response.status_code == 403
    still = await platform_settings_service.get_maintenance(test_db, force=True)
    assert still["enabled"] is True


async def test_b31_admin_login_works_during_maintenance(anon_client, admin_user, test_db):
    await _seed_maintenance(test_db, enabled=True)
    response = anon_client.post(
        "/api/v1/admin/auth/login",
        json={"username": "testadmin", "password": "admin-test-password"},
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Public status payload (§12.4 / §17)
# ---------------------------------------------------------------------------


async def test_public_status_shape_and_no_internals(anon_client, test_db):
    suffix = uuid.uuid4().hex[:8]
    slug = f"maint-test-{suffix}"
    await _seed_maintenance(
        test_db,
        enabled=True,
        title="Upgrades",
        message="Back soon",
        expected_return_at="2026-01-01T10:00:00+00:00",
        reason="internal only",
    )
    flag = FeatureFlag(key=f"flag-{suffix}", status="maintenance", message="wip")
    provider = ProviderRegistry(
        name=f"maintp-{suffix}",
        display_name="Maintenance Test Provider",
        slug=slug,
        litellm_provider="openai",
        default_model="gpt-4o-mini",
        priority=99,
        is_enabled=False,
        status="disabled",
        status_message="Off for testing",
        status_expires_at=datetime(2026, 1, 1, tzinfo=UTC),
        allow_key_addition=False,
    )
    test_db.add(flag)
    test_db.add(provider)
    await test_db.commit()

    try:
        response = anon_client.get("/api/v1/platform/status")
        assert response.status_code == 200
        body = response.json()

        maintenance = body["maintenance"]
        assert set(maintenance.keys()) == {
            "enabled",
            "title",
            "message",
            "expected_return_at",
        }
        assert maintenance["enabled"] is True
        assert maintenance["title"] == "Upgrades"
        assert "reason" not in maintenance

        assert body["features"][flag.key] == "maintenance"

        entry = next(
            item for item in body["disabled_providers"] if item["slug"] == slug
        )
        assert entry["message"] == "Off for testing"
        assert entry["expires_at"] is not None
        assert "changed_by" not in entry
    finally:
        await test_db.delete(flag)
        await test_db.delete(provider)
        await test_db.commit()


# ---------------------------------------------------------------------------
# B26 — worker claim gate (§12.3)
# ---------------------------------------------------------------------------


async def test_b26_worker_stops_claiming_and_resumes(worker_env):
    repo = await _seed_repo(worker_env, name="maint-repo", gid=9201, install_id=92001)
    job = await _seed_job(worker_env, repo, 1)

    async with worker_env() as db:
        state, _prior, conflict = await platform_settings_service.set_maintenance(
            db, {"enabled": True}
        )
        assert conflict is None
        await db.commit()

    # Queued job must not be claimed while maintenance is on.
    assert await claim_next_job_with_factory(worker_env) is None
    status, completed_at = await _job_status(worker_env, job.id)
    assert status == JobStatus.QUEUED
    assert completed_at is None
    assert await _job_count(worker_env) == 1

    # Disable → the same job is claimed exactly once, no duplication.
    async with worker_env() as db:
        await platform_settings_service.set_maintenance(db, {"enabled": False})
        await db.commit()

    claimed = await claim_next_job_with_factory(worker_env)
    assert claimed is not None
    assert claimed[0] == job.id
    status, _ = await _job_status(worker_env, job.id)
    assert status == JobStatus.RUNNING
    assert await _job_count(worker_env) == 1


async def test_b26_inflight_job_untouched_by_gate(worker_env):
    repo = await _seed_repo(worker_env, name="maint-run", gid=9202, install_id=92002)
    running = await _seed_job(worker_env, repo, 2, status=JobStatus.RUNNING)

    async with worker_env() as db:
        await platform_settings_service.set_maintenance(db, {"enabled": True})
        await db.commit()

    assert await claim_next_job_with_factory(worker_env) is None
    status, completed_at = await _job_status(worker_env, running.id)
    assert status == JobStatus.RUNNING
    assert completed_at is None
    assert await _job_count(worker_env) == 1
