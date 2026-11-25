"""Deterministic tests for kLLM advisory locking and global load capacity.

All coordination is simulated in memory. No PostgreSQL server, kLLM relay or
model operation is used.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.services import kllm_autoload as ka
from app.services.kllm_service import KllmUnavailableError

MODEL = "qwen3.8-27b"


def _statement_key(stmt) -> int:
    compiled = stmt.compile()
    params = list(compiled.params.values())
    assert params, f"No bound parameter in {compiled}"
    return int(params[0])


class FakeDialect:
    name = "postgresql"
    driver = "asyncpg"
    is_async = True


class FakeSyncEngine:
    """Minimal sync engine stand-in; AsyncEngine proxies ``dialect`` to it."""

    def __init__(self):
        self.dialect = FakeDialect()


class FakeRegistry:
    def __init__(self):
        self.held: dict[int, str] = {}
        self.lookup_error = False
        self.unlock_error = False
        self.try_calls = 0
        self.unlock_calls = 0
        self.lock_connection: dict[int, str] = {}
        self.unlock_connection: dict[int, str] = {}
        self.invalidated: set[str] = set()

    def release_connection(self, connection_id: str) -> None:
        for key in [
            key for key, owner in self.held.items() if owner == connection_id
        ]:
            self.held.pop(key, None)


class FakeConnection:
    def __init__(self, registry: FakeRegistry):
        self.registry = registry
        self.connection_id = str(uuid.uuid4())

    async def scalar(self, stmt):
        compiled = str(stmt.compile())
        key = _statement_key(stmt)
        if self.registry.lookup_error and "pg_try_advisory_lock" in compiled:
            raise RuntimeError("simulated lookup failure")
        if "pg_try_advisory_lock" in compiled:
            self.registry.try_calls += 1
            owner = self.registry.held.get(key)
            if owner is not None and owner != self.connection_id:
                return False
            self.registry.held[key] = self.connection_id
            self.registry.lock_connection[key] = self.connection_id
            return True
        if "pg_advisory_unlock" in compiled:
            return self._unlock(key)
        raise AssertionError(f"Unexpected statement: {compiled}")

    async def execute(self, stmt):
        compiled = str(stmt.compile())
        if "pg_advisory_unlock" in compiled:
            self._unlock(_statement_key(stmt))

    def _unlock(self, key: int) -> bool:
        self.registry.unlock_calls += 1
        self.registry.unlock_connection[key] = self.connection_id
        if self.registry.unlock_error:
            return False
        if self.registry.held.get(key) == self.connection_id:
            self.registry.held.pop(key, None)
        return True

    async def commit(self):
        return None

    async def invalidate(self):
        self.registry.invalidated.add(self.connection_id)
        self.registry.release_connection(self.connection_id)

    async def close(self):
        return None


class FakeConnectionContext:
    def __init__(self, registry: FakeRegistry):
        self.registry = registry
        self.connection = FakeConnection(registry)

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_exc):
        await self.connection.close()


class FakeEngine(AsyncEngine):
    """AsyncEngine subclass whose connect() yields the in-memory fake connection.

    kllm_autoload pins one physical connection for advisory locks and requires
    a genuine AsyncEngine (a sync Engine would raise MissingGreenlet).
    """

    def __init__(self, registry: FakeRegistry):
        super().__init__(FakeSyncEngine())
        self.registry = registry

    def connect(self):
        return FakeConnectionContext(self.registry)


class FakeDB:
    def __init__(self, registry: FakeRegistry):
        self._engine = FakeEngine(registry)
        self.bind = self._engine
        self.commits = 0

    def get_bind(self):
        return self._engine

    async def commit(self):
        self.commits += 1


def _model_key(model: str = MODEL) -> int:
    import zlib

    return zlib.crc32(f"revora:kllm:lifecycle:{model}".encode()) & 0x7FFFFFFF


@pytest.fixture(autouse=True)
def _fast_advisory_retries(monkeypatch):
    monkeypatch.setattr(ka, "_ADVISORY_LOCK_ATTEMPTS", 3)
    monkeypatch.setattr(ka, "_ADVISORY_LOCK_RETRY_SECONDS", 0)
    monkeypatch.setattr(ka, "_GLOBAL_SLOT_LOCK_ATTEMPTS", 3)
    monkeypatch.setattr(ka, "_GLOBAL_SLOT_RETRY_SECONDS", 0)
    monkeypatch.setattr(ka, "_model_locks", {})


async def test_advisory_lock_success_and_release():
    registry = FakeRegistry()
    db = FakeDB(registry)
    key = _model_key()
    entered = False
    async with ka.model_operation_lock(db, MODEL):
        entered = True
        assert registry.held[key] == registry.lock_connection[key]
    assert entered is True
    assert registry.held == {}
    assert registry.unlock_connection[key] == registry.lock_connection[key]


async def test_advisory_lock_contention_fails_closed():
    registry = FakeRegistry()
    registry.held[_model_key()] = "another-process"
    db = FakeDB(registry)
    entered = False
    with pytest.raises(KllmUnavailableError) as exc:
        async with ka.model_operation_lock(db, MODEL):
            entered = True
    assert exc.value.reason_code == "lifecycle_lock_busy"
    assert entered is False
    assert registry.try_calls == 3


async def test_advisory_lock_lookup_error_fails_closed():
    registry = FakeRegistry()
    registry.lookup_error = True
    db = FakeDB(registry)
    entered = False
    with pytest.raises(KllmUnavailableError) as exc:
        async with ka.model_operation_lock(db, MODEL):
            entered = True
    assert exc.value.reason_code == "lifecycle_lock_unavailable"
    assert entered is False


async def test_advisory_lock_released_on_exception_and_cancellation():
    registry = FakeRegistry()
    db = FakeDB(registry)
    key = _model_key()
    with pytest.raises(ValueError):
        async with ka.model_operation_lock(db, MODEL):
            raise ValueError("boom")
    assert registry.held == {}

    with pytest.raises(asyncio.CancelledError):
        async with ka.model_operation_lock(db, MODEL):
            raise asyncio.CancelledError()
    assert registry.held == {}
    assert registry.unlock_calls >= 2


async def test_commit_inside_lock_keeps_same_pinned_connection():
    registry = FakeRegistry()
    db = FakeDB(registry)
    key = _model_key()
    async with ka.model_operation_lock(db, MODEL):
        await db.commit()
        assert db.commits == 1
        assert registry.held[key] == registry.lock_connection[key]
    assert registry.held == {}
    assert registry.unlock_connection[key] == registry.lock_connection[key]


async def test_unlock_failure_invalidates_connection_and_releases_lock():
    registry = FakeRegistry()
    db = FakeDB(registry)
    key = _model_key()
    async with ka.model_operation_lock(db, MODEL):
        registry.unlock_error = True
    assert registry.held == {}
    assert registry.lock_connection[key] in registry.invalidated


async def test_no_lifecycle_operation_without_distributed_protection(monkeypatch):
    registry = FakeRegistry()
    registry.lookup_error = True
    db = FakeDB(registry)
    calls = []

    async def forbidden(*_args, **_kwargs):
        calls.append(True)

    monkeypatch.setattr(ka, "_assert_load_allowed", forbidden)
    monkeypatch.setattr(ka.kllm_service, "request_model_load", forbidden)

    with pytest.raises(KllmUnavailableError):
        async with ka.model_operation_lock(db, MODEL):
            await ka._request_load_once(
                db, MODEL, {"max_concurrent_loads": 1, "version": 1}
            )
    assert calls == []


def _policy(limit: int, version: int = 1):
    return {"max_concurrent_loads": limit, "version": version}


def _policy_reader(policy):
    async def reader(db=None, *, force=True):
        return policy

    return reader


async def test_global_limit_one_across_simulated_processes(monkeypatch):
    registry = FakeRegistry()
    db_a, db_b = FakeDB(registry), FakeDB(registry)
    policy = _policy(1)
    monkeypatch.setattr(ka, "get_policy", _policy_reader(policy))

    async with ka._global_capacity(db_a, policy):
        with pytest.raises(KllmUnavailableError) as exc:
            async with ka._global_capacity(db_b, policy):
                pytest.fail("second process must not acquire capacity")
    assert exc.value.reason_code == "global_load_limit_busy"
    assert registry.held == {}


async def test_global_limit_n_across_simulated_processes(monkeypatch):
    registry = FakeRegistry()
    policy = _policy(2)
    monkeypatch.setattr(ka, "get_policy", _policy_reader(policy))
    acquired = asyncio.Event()
    release = asyncio.Event()

    async def holder(db):
        async with ka._global_capacity(db, policy):
            acquired.set()
            await release.wait()

    tasks = [asyncio.create_task(holder(FakeDB(registry))) for _ in range(2)]
    await asyncio.wait_for(acquired.wait(), timeout=1)
    await asyncio.sleep(0)
    with pytest.raises(KllmUnavailableError) as exc:
        async with ka._global_capacity(FakeDB(registry), policy):
            pytest.fail("third process must not acquire capacity")
    assert exc.value.reason_code == "global_load_limit_busy"
    release.set()
    await asyncio.gather(*tasks)
    assert registry.held == {}


async def test_policy_version_change_is_rechecked_after_slot_acquisition(
    monkeypatch,
):
    registry = FakeRegistry()
    old_policy = _policy(2, 1)
    fresh_policy = _policy(2, 2)
    reads = 0

    async def fake_policy(db=None, *, force=True):
        nonlocal reads
        reads += 1
        return fresh_policy

    monkeypatch.setattr(ka, "get_policy", fake_policy)
    async with ka._global_capacity(FakeDB(registry), old_policy):
        # First read detects the version change; the retry uses fresh policy.
        assert reads == 2
    assert registry.held == {}


async def test_waiter_cancellation_releases_global_capacity(monkeypatch):
    registry = FakeRegistry()
    monkeypatch.setattr(ka, "_GLOBAL_SLOT_LOCK_ATTEMPTS", 100)
    monkeypatch.setattr(ka, "_GLOBAL_SLOT_RETRY_SECONDS", 0.01)
    policy = _policy(1)
    monkeypatch.setattr(ka, "get_policy", _policy_reader(policy))
    release = asyncio.Event()

    async def holder():
        async with ka._global_capacity(FakeDB(registry), policy):
            await release.wait()

    task = asyncio.create_task(holder())
    await asyncio.sleep(0.05)
    waiter = asyncio.create_task(
        ka._global_capacity(FakeDB(registry), policy).__aenter__()
    )
    await asyncio.sleep(0.05)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    release.set()
    await task
    assert registry.held == {}


async def test_global_capacity_released_on_exception(monkeypatch):
    registry = FakeRegistry()
    policy = _policy(1)
    monkeypatch.setattr(ka, "get_policy", _policy_reader(policy))
    with pytest.raises(ValueError):
        async with ka._global_capacity(FakeDB(registry), policy):
            raise ValueError("load request failed")
    assert registry.held == {}


async def test_global_coordination_failure_fails_closed(monkeypatch):
    registry = FakeRegistry()
    registry.lookup_error = True
    policy = _policy(1)
    monkeypatch.setattr(ka, "get_policy", _policy_reader(policy))
    with pytest.raises(KllmUnavailableError) as exc:
        async with ka._global_capacity(FakeDB(registry), policy):
            pytest.fail("capacity must not be granted when coordination fails")
    assert exc.value.reason_code == "global_load_gate_unavailable"


async def test_policy_limit_change_quiesces_global_slots(monkeypatch):
    registry = FakeRegistry()
    policy = _policy(1)
    monkeypatch.setattr(ka, "get_policy", _policy_reader(policy))
    release = asyncio.Event()
    holder_task = asyncio.create_task(
        _hold_capacity(FakeDB(registry), policy, release)
    )
    await asyncio.sleep(0.05)
    with pytest.raises(ka.KllmConflictError) as exc:
        async with ka.hold_global_load_gate(FakeDB(registry)):
            pytest.fail("gate must not open while loads are active")
    assert exc.value.reason_code == "global_loads_active"
    release.set()
    await holder_task


async def _hold_capacity(db, policy, release):
    async with ka._global_capacity(db, policy):
        await release.wait()
