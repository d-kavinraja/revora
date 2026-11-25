"""Mocked tests for session-aware hosted monitoring and automatic wake.

No test contacts Ollama, wakes a real machine, loads a model or runs inference.
All network, Redis and wake boundaries are mocked or hermetic.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai import hosted_ollama_client as hclient
from app.core import config as config_module
from app.models.platform import PlatformSetting
from app.services import hosted_monitor, hosted_ollama_service as hosted
from app.services import user_presence

BASE = "http://hosted.test:11434"
_REAL_WAIT_FOR_READY = hosted.wait_for_ready


def _probe(ok, category="transport", version="0.40.17", error="Hosted Ollama is unreachable."):
    return hosted.HostedProbe(ok, category, version=version, error=error)


def _snapshot(reachable=True, version="0.40.17"):
    return hosted.HostedSnapshot(
        enabled=True,
        configured=True,
        reachable=reachable,
        stale=False,
        generated_at=datetime.now(UTC),
        age_seconds=0.0,
        error=None,
        models=[],
        selection_enabled=True,
        wake_enabled=True,
        waking=False,
        version=version,
        concurrency=hosted.concurrency_status(),
    )


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    for key, value in {
        "REVORA_HOSTED_MONITOR_ENABLED": True,
        "REVORA_HOSTED_OLLAMA_ENABLED": True,
        "REVORA_HOSTED_WAKE_ENABLED": True,
        "REVORA_HOSTED_MONITOR_INTERVAL_S": 20.0,
        "REVORA_HOSTED_READY_TIMEOUT_S": 5.0,
        "REVORA_HOSTED_READY_POLL_INTERVAL_S": 0.1,
        "REVORA_HOSTED_WAKE_COOLDOWN_S": 60.0,
        "REDIS_URL": None,
    }.items():
        monkeypatch.setattr(config_module.settings, key, value, raising=False)
    hosted_monitor.reset_runtime_state()
    hosted.reset_runtime_state()
    yield
    hosted_monitor.reset_runtime_state()


@pytest.fixture
async def db(test_db, monkeypatch):
    # Clear shared-state rows between tests: our helpers commit on sessions
    # bound to the test connection, which can outlive a single test transaction.
    factory = async_sessionmaker(
        bind=test_db.bind, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )

    from sqlalchemy import delete

    async with factory() as session:
        await session.execute(
            delete(PlatformSetting).where(
                PlatformSetting.key.in_([hosted_monitor.STATE_KEY, hosted_monitor.COORD_KEY])
            )
        )
        await session.commit()

    @asynccontextmanager
    async def _cm():
        async with factory() as session:
            yield session

    monkeypatch.setattr(hosted_monitor, "AsyncSessionLocal", _cm)
    return test_db


@pytest.fixture
def env(monkeypatch, db):
    """Install default healthy mocks and record calls at every boundary."""
    calls = {"probe": 0, "wake": 0, "ready": 0, "snapshot": 0, "load": 0}

    async def has_session(*a, **k):
        return True

    async def enabled(db=None):
        return True

    async def probe():
        calls["probe"] += 1
        return _probe(True)

    async def snapshot(db=None, force=False):
        calls["snapshot"] += 1
        return _snapshot()

    async def wake():
        calls["wake"] += 1
        return hosted.WakeResult(True)

    async def ready():
        calls["ready"] += 1
        return True

    async def redis():
        return None

    monkeypatch.setattr(user_presence, "has_active_session", has_session)
    monkeypatch.setattr(hosted, "is_enabled", enabled)
    monkeypatch.setattr(hosted, "probe_ollama", probe)
    monkeypatch.setattr(hosted, "get_snapshot", snapshot)
    monkeypatch.setattr(hosted, "call_wake", wake)
    monkeypatch.setattr(hosted, "wait_for_ready", ready)
    monkeypatch.setattr(hosted, "redis_client", redis)
    monkeypatch.setattr(
        hosted, "wake_status",
        lambda: {"enabled": True, "configured": True, "waking": False, "last_error": None},
    )

    async def never(*a, **k):
        calls["load"] += 1
        raise AssertionError("model load/inference must never be called by monitoring")

    # The monitor must never touch the inference client.
    monkeypatch.setattr(hclient.hosted_ollama_client, "complete", never)
    monkeypatch.setattr(hclient.hosted_ollama_client, "stream", never)
    return calls


async def _cycle():
    await hosted_monitor._monitor_cycle()


# --- heartbeat integration --------------------------------------------------


async def test_authenticated_heartbeat_schedules_monitor(anon_client, user_auth_token, monkeypatch):
    scheduled = []
    monkeypatch.setattr(
        hosted_monitor, "notify_session_activity", lambda: scheduled.append(True) or True
    )
    response = anon_client.post(
        "/api/v1/kllm/session/heartbeat",
        headers={"Authorization": f"Bearer {user_auth_token}"},
        json={"client_session_id": str(uuid.uuid4()), "active": True},
    )
    assert response.status_code == 200, response.text
    assert len(scheduled) == 1


async def test_unauthenticated_heartbeat_never_schedules_monitor(anon_client, monkeypatch):
    scheduled = []
    monkeypatch.setattr(
        hosted_monitor, "notify_session_activity", lambda: scheduled.append(True) or True
    )
    response = anon_client.post(
        "/api/v1/kllm/session/heartbeat",
        json={"client_session_id": str(uuid.uuid4()), "active": True},
    )
    assert response.status_code == 401
    assert scheduled == []


async def test_heartbeat_inactive_session_still_succeeds(anon_client, user_auth_token, monkeypatch):
    monkeypatch.setattr(hosted_monitor, "notify_session_activity", lambda: True)
    response = anon_client.post(
        "/api/v1/kllm/session/heartbeat",
        headers={"Authorization": f"Bearer {user_auth_token}"},
        json={"client_session_id": str(uuid.uuid4()), "active": False},
    )
    assert response.status_code == 200
    assert response.json()["session"]["active"] is False


def test_monitor_disabled_does_not_schedule(monkeypatch):
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_MONITOR_ENABLED", False, raising=False)
    assert hosted_monitor.notify_session_activity() is False


async def test_duplicate_notifications_dedupe(monkeypatch):
    async def fake_cycle():
        await asyncio.sleep(0.01)

    monkeypatch.setattr(hosted_monitor, "_monitor_cycle", fake_cycle)
    assert hosted_monitor.notify_session_activity() is True
    assert hosted_monitor.notify_session_activity() is False
    task = hosted_monitor._pending_task
    if task:
        await task
    hosted_monitor.reset_runtime_state()


# --- gating -----------------------------------------------------------------


async def test_no_active_session_skips_everything(env, monkeypatch):
    async def inactive(*a, **k):
        return False

    monkeypatch.setattr(user_presence, "has_active_session", inactive)
    await _cycle()
    assert env["probe"] == 0
    assert env["wake"] == 0


async def test_hosted_disabled_sets_state(env, monkeypatch):
    async def disabled(db=None):
        return False

    monkeypatch.setattr(hosted, "is_enabled", disabled)
    await _cycle()
    assert (await hosted_monitor.get_state(force=True))["state"] == "disabled"
    assert env["probe"] == 0
    assert env["wake"] == 0


async def test_admin_selection_disabled_blocks_wake(env, monkeypatch):
    async def disabled(db=None):
        return False

    monkeypatch.setattr(hosted, "is_enabled", disabled)
    await _cycle()
    assert env["wake"] == 0


# --- healthy / discovery ----------------------------------------------------


async def test_healthy_probe_sets_connected(env):
    await _cycle()
    state = await hosted_monitor.get_state(force=True)
    assert state["state"] == "connected"
    assert state["version"] == "0.40.17"
    assert state["discovery_ok"] is True
    assert state["last_success_at"] is not None
    assert env["wake"] == 0
    assert env["load"] == 0


async def test_discovery_failure_with_healthy_probe_sets_error(env, monkeypatch):
    async def bad_snapshot(db=None, force=False):
        return _snapshot(reachable=False)

    monkeypatch.setattr(hosted, "get_snapshot", bad_snapshot)
    await _cycle()
    state = await hosted_monitor.get_state(force=True)
    assert state["state"] == "error"
    assert state["discovery_ok"] is False
    assert env["wake"] == 0


# --- failure classification / wake -----------------------------------------


@pytest.mark.parametrize("category", ["config", "auth", "http", "invalid"])
async def test_non_transport_failure_never_wakes(env, monkeypatch, category):
    async def failed_probe():
        return _probe(False, category=category, error="safe failure reason")

    monkeypatch.setattr(hosted, "probe_ollama", failed_probe)
    await _cycle()
    assert env["wake"] == 0
    assert (await hosted_monitor.get_state(force=True))["state"] == "error"


async def test_transport_failure_wakes_and_connects(env, monkeypatch):
    async def failed_probe():
        return _probe(False, category="transport")

    monkeypatch.setattr(hosted, "probe_ollama", failed_probe)
    await _cycle()
    state = await hosted_monitor.get_state(force=True)
    assert state["state"] == "connected"
    assert env["wake"] == 1
    assert env["ready"] == 1
    assert env["snapshot"] >= 1
    assert env["load"] == 0


async def test_wake_disabled_reports_unreachable(env, monkeypatch):
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_WAKE_ENABLED", False, raising=False)

    async def failed_probe():
        return _probe(False, category="transport")

    monkeypatch.setattr(hosted, "probe_ollama", failed_probe)
    await _cycle()
    assert (await hosted_monitor.get_state(force=True))["state"] == "unreachable"
    assert env["wake"] == 0


async def test_wake_not_configured_reports_unreachable(env, monkeypatch):
    monkeypatch.setattr(hosted, "wake_status", lambda: {
        "enabled": True, "configured": False, "waking": False, "last_error": None
    })

    async def failed_probe():
        return _probe(False, category="transport")

    monkeypatch.setattr(hosted, "probe_ollama", failed_probe)
    await _cycle()
    assert (await hosted_monitor.get_state(force=True))["state"] == "unreachable"
    assert env["wake"] == 0


async def test_wake_failure_sets_cooldown(env, monkeypatch):
    async def failed_probe():
        return _probe(False, category="transport")

    async def failed_wake():
        return hosted.WakeResult(False, error="Wake request failed.")

    monkeypatch.setattr(hosted, "probe_ollama", failed_probe)
    monkeypatch.setattr(hosted, "call_wake", failed_wake)
    await _cycle()
    state = await hosted_monitor.get_state(force=True)
    assert state["state"] == "error"
    assert state["cooldown_until"] is not None
    assert await hosted_monitor.get_cooldown() > 0
    assert env["ready"] == 0


async def test_wake_api_cooldown_is_persisted_and_respected(env, monkeypatch):
    async def failed_probe():
        return _probe(False, category="transport")

    async def cooldown_wake():
        env["wake"] += 1
        return hosted.WakeResult(
            False, error="The hosted machine is cooling down.", retry_after=120.0
        )

    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_MONITOR_INTERVAL_S", 0.01, raising=False)
    monkeypatch.setattr(hosted, "probe_ollama", failed_probe)
    monkeypatch.setattr(hosted, "call_wake", cooldown_wake)
    await _cycle()
    assert (await hosted_monitor.get_state(force=True))["state"] in {"error", "wake_cooldown"}

    # Let the short tick lease expire, then verify the persisted cooldown
    # prevents a second wake API call.
    await asyncio.sleep(0.03)
    await _cycle()
    assert env["wake"] == 1
    assert (await hosted_monitor.get_state(force=True))["state"] == "wake_cooldown"


async def test_wake_conflict_does_not_poll_readiness(env, monkeypatch):
    async def failed_probe():
        return _probe(False, category="transport")

    async def conflict_wake():
        return hosted.WakeResult(False, error="operation_conflict", conflict=True)

    monkeypatch.setattr(hosted, "probe_ollama", failed_probe)
    monkeypatch.setattr(hosted, "call_wake", conflict_wake)
    await _cycle()
    assert env["ready"] == 0
    assert (await hosted_monitor.get_state(force=True))["state"] == "waking"


async def test_ollama_not_ready_after_wake(env, monkeypatch):
    async def failed_probe():
        return _probe(False, category="transport")

    async def not_ready():
        return False

    monkeypatch.setattr(hosted, "probe_ollama", failed_probe)
    monkeypatch.setattr(hosted, "wait_for_ready", not_ready)
    await _cycle()
    state = await hosted_monitor.get_state(force=True)
    assert state["state"] == "unreachable"
    assert state["discovery_ok"] is False


async def test_discovery_failure_after_wake(env, monkeypatch):
    async def failed_probe():
        return _probe(False, category="transport")

    async def bad_snapshot(db=None, force=False):
        return _snapshot(reachable=False)

    monkeypatch.setattr(hosted, "probe_ollama", failed_probe)
    monkeypatch.setattr(hosted, "get_snapshot", bad_snapshot)
    await _cycle()
    assert (await hosted_monitor.get_state(force=True))["state"] == "error"


async def test_wake_timeout_is_bounded(env, monkeypatch):
    async def failed_probe():
        return _probe(False, category="transport")

    # The real (bounded) waiter must stop at READY_TIMEOUT, not loop forever.
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_READY_TIMEOUT_S", 0.08, raising=False)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_READY_POLL_INTERVAL_S", 0.02, raising=False)
    monkeypatch.setattr(hosted, "probe_ollama", failed_probe)
    monkeypatch.setattr(hosted, "wait_for_ready", _REAL_WAIT_FOR_READY)
    await asyncio.wait_for(_cycle(), timeout=2)
    assert (await hosted_monitor.get_state(force=True))["state"] == "unreachable"


# --- coordination -----------------------------------------------------------


async def test_minimum_interval_dedups_cycles(env, monkeypatch):
    probes = []

    async def failed_probe():
        probes.append(1)
        return _probe(False, category="transport")

    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_MONITOR_INTERVAL_S", 0.5, raising=False)
    monkeypatch.setattr(hosted, "probe_ollama", failed_probe)
    await _cycle()
    assert len(probes) == 1
    await _cycle()
    assert len(probes) == 1
    assert env["wake"] == 1


async def test_concurrent_wake_dedup_db_fallback(monkeypatch, env):
    async def failed_probe():
        return _probe(False, category="transport")

    async def slow_wake():
        env["wake"] += 1
        await asyncio.sleep(0.05)
        return hosted.WakeResult(True)

    monkeypatch.setattr(hosted, "probe_ollama", failed_probe)
    monkeypatch.setattr(hosted, "call_wake", slow_wake)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_MONITOR_INTERVAL_S", 5.0, raising=False)
    await asyncio.gather(_cycle(), _cycle())
    assert env["wake"] == 1


async def test_redis_coordination_used_when_available(monkeypatch, env):
    class FakeRedis:
        def __init__(self):
            self.store = {}

        async def set(self, key, value, nx=False, ex=None):
            if nx and key in self.store:
                return None
            self.store[key] = value
            return True

        async def eval(self, script, nkeys, key, owner):
            if self.store.get(key) == owner:
                del self.store[key]
                return 1
            return 0

    fake = FakeRedis()

    async def redis():
        return fake

    monkeypatch.setattr(hosted, "redis_client", redis)
    await _cycle()
    state = await hosted_monitor.get_state(force=True)
    assert state["state"] == "connected"
    assert any(k.startswith("revora:hosted:monitor:tick") for k in fake.store)


async def test_redis_unavailable_uses_db_fallback(monkeypatch, env, db):
    await _cycle()
    row = (
        await db.execute(
            select(PlatformSetting).where(PlatformSetting.key == hosted_monitor.COORD_KEY)
        )
    ).scalars().first()
    assert row is not None
    assert "tick_until" in row.value


async def test_db_lease_expiry_allows_reacquire(monkeypatch, db):
    assert await hosted_monitor._claim_db("wake", 0.01, "owner-a") is True
    assert await hosted_monitor._claim_db("wake", 0.01, "owner-b") is False
    await asyncio.sleep(0.03)
    assert await hosted_monitor._claim_db("wake", 0.01, "owner-b") is True


async def test_redis_lease_release_is_owner_checked(monkeypatch, env):
    class FakeRedis:
        def __init__(self):
            self.store = {}

        async def set(self, key, value, nx=False, ex=None):
            self.store[key] = value
            return True

        async def eval(self, script, nkeys, key, owner):
            if self.store.get(key) == owner:
                del self.store[key]
                return 1
            return 0

    fake = FakeRedis()

    async def redis():
        return fake

    monkeypatch.setattr(hosted, "redis_client", redis)
    acquired, owner, mode = await hosted_monitor._claim("wake", 10)
    assert acquired is True and mode == "redis"
    await hosted_monitor._release("wake", "someone-else", mode)
    assert f"revora:hosted:monitor:wake" in fake.store
    await hosted_monitor._release("wake", owner, mode)
    assert "revora:hosted:monitor:wake" not in fake.store


# --- shared state / security ------------------------------------------------


async def test_shared_state_has_no_secrets_or_endpoint(env, monkeypatch):
    monkeypatch.setattr(
        config_module.settings, "REVORA_HOSTED_OLLAMA_URL_TOKEN", "secret-token-value",
        raising=False,
    )
    state = await hosted_monitor.get_state(force=True)
    text = str(state)
    assert BASE not in text
    assert "secret-token-value" not in text
    assert "ibk_" not in text
    assert "_token" not in text


async def test_state_transitions_are_recorded(monkeypatch, env):
    async def failed_probe():
        return _probe(False, category="transport")

    monkeypatch.setattr(hosted, "probe_ollama", failed_probe)
    await _cycle()
    state = await hosted_monitor.get_state(force=True)
    assert state["last_monitor_at"] is not None
    assert state["last_wake_at"] is not None
    assert state["state"] == "connected"
    # reason is cleared on a successful, verified connection.


async def test_persisted_state_survives_cache_reset(env, db):
    await hosted_monitor.set_state(state="connected", version="9.9.9")
    hosted_monitor.reset_runtime_state()
    state = await hosted_monitor.get_state(force=True)
    assert state["state"] == "connected"
    assert state["version"] == "9.9.9"
