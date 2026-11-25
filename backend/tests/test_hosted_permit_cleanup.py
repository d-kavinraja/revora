"""Cancellation-safety tests for the hosted Ollama concurrency permit.

A permit is a pair (global + per-model). Cancelling a request while it is still
acquiring, or while its body runs, must never leak either half: a leaked global
slot permanently shrinks capacity for every later chat.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core import config as config_module
from app.services import hosted_ollama_service as hosted
from app.services.hosted_ollama_service import HostedBusyError, permit


@pytest.fixture(autouse=True)
def _reset_gate(monkeypatch):
    hosted.reset_runtime_state()
    yield
    hosted.reset_runtime_state()


class _FakeRedis:
    """Blocks on the per-model acquisition so the test can cancel mid-pair."""

    def __init__(self) -> None:
        self.global_key: str | None = None
        self.model_key: str | None = None
        self.tokens: list[str] = []
        self.removed: list[tuple[str, str]] = []
        self._evals = 0
        self.model_attempted = asyncio.Event()

    async def eval(self, script, numkeys, key, now, expires, limit, token):
        self._evals += 1
        self.tokens.append(token)
        if self._evals == 1:
            self.global_key = key
            return 1
        self.model_key = key
        self.model_attempted.set()
        await asyncio.Event().wait()  # cancelled here
        return 1

    async def zrem(self, key, token):
        self.removed.append((key, token))


async def _use_permit(model: str = "demo:7b", *, entered: asyncio.Event | None = None):
    async with permit(model):
        if entered is not None:
            entered.set()
        await asyncio.Event().wait()


async def test_cancellation_during_redis_pair_releases_the_global_slot(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(hosted, "_resolve_gate_mode", lambda: _ready("redis"))
    monkeypatch.setattr(hosted, "_get_redis", lambda: _ready(fake))

    task = asyncio.create_task(_use_permit())
    await fake.model_attempted.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert fake.global_key is not None
    token = fake.tokens[0]
    removed_keys = {key for key, removed_token in fake.removed if removed_token == token}
    assert fake.global_key in removed_keys
    assert fake.model_key in removed_keys
    assert hosted._queued == 0
    assert hosted._inflight_global == 0


async def test_redis_permit_still_releases_on_normal_exit(monkeypatch):
    class _ImmediateRedis(_FakeRedis):
        async def eval(self, script, numkeys, key, now, expires, limit, token):
            self._evals += 1
            self.tokens.append(token)
            if self._evals % 2 == 1:
                self.global_key = key
            else:
                self.model_key = key
            return 1

    fake = _ImmediateRedis()
    monkeypatch.setattr(hosted, "_resolve_gate_mode", lambda: _ready("redis"))
    monkeypatch.setattr(hosted, "_get_redis", lambda: _ready(fake))

    async with permit("demo:7b"):
        assert hosted._inflight_global == 1

    assert hosted._inflight_global == 0
    assert {key for key, _ in fake.removed} == {fake.global_key, fake.model_key}


async def test_cancellation_while_waiting_for_the_global_local_slot_leaks_nothing(monkeypatch):
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_MAX_CONCURRENT_REQUESTS", 1)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_MAX_CONCURRENT_REQUESTS_PER_MODEL", 1)
    monkeypatch.setattr(hosted, "_resolve_gate_mode", lambda: _ready("local"))
    hosted.reset_runtime_state()
    entered = asyncio.Event()

    holder = asyncio.create_task(_use_permit(entered=entered))
    await entered.wait()

    waiter = asyncio.create_task(_use_permit())
    await asyncio.sleep(0.05)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    assert hosted._global_semaphore()._value == 0  # only the holder
    holder.cancel()
    with pytest.raises(asyncio.CancelledError):
        await holder
    assert hosted._global_semaphore()._value == 1
    assert hosted._queued == 0


async def test_cancellation_after_global_but_before_model_slot_releases_global(monkeypatch):
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_MAX_CONCURRENT_REQUESTS", 2)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_MAX_CONCURRENT_REQUESTS_PER_MODEL", 1)
    monkeypatch.setattr(hosted, "_resolve_gate_mode", lambda: _ready("local"))
    hosted.reset_runtime_state()
    entered = asyncio.Event()

    holder = asyncio.create_task(_use_permit(entered=entered))
    await entered.wait()
    assert hosted._global_semaphore()._value == 1
    assert hosted._model_semaphore("demo:7b")._value == 0

    waiter = asyncio.create_task(_use_permit())
    await asyncio.sleep(0.05)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    # The waiter took the second global slot, then was cancelled on the model
    # slot; that global slot must come back while the holder keeps its own.
    assert hosted._global_semaphore()._value == 1
    assert hosted._model_semaphore("demo:7b")._value == 0

    holder.cancel()
    with pytest.raises(asyncio.CancelledError):
        await holder
    assert hosted._global_semaphore()._value == 2
    assert hosted._model_semaphore("demo:7b")._value == 1


async def test_cancellation_inside_the_body_still_releases_the_permit(monkeypatch):
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_MAX_CONCURRENT_REQUESTS", 2)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_MAX_CONCURRENT_REQUESTS_PER_MODEL", 1)
    monkeypatch.setattr(hosted, "_resolve_gate_mode", lambda: _ready("local"))
    hosted.reset_runtime_state()
    entered = asyncio.Event()

    task = asyncio.create_task(_use_permit(entered=entered))
    await entered.wait()
    assert hosted._inflight_global == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert hosted._inflight_global == 0
    assert hosted._global_semaphore()._value == 2
    assert hosted._model_semaphore("demo:7b")._value == 1
    # Capacity is genuinely usable again.
    async with permit("demo:7b"):
        pass


async def test_capacity_limit_still_reports_busy(monkeypatch):
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_MAX_CONCURRENT_REQUESTS", 1)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_MAX_CONCURRENT_REQUESTS_PER_MODEL", 1)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_QUEUE_TIMEOUT_S", 0.05)
    monkeypatch.setattr(hosted, "_resolve_gate_mode", lambda: _ready("local"))
    hosted.reset_runtime_state()
    entered = asyncio.Event()

    holder = asyncio.create_task(_use_permit(entered=entered))
    await entered.wait()
    with pytest.raises(HostedBusyError):
        async with permit("demo:7b"):
            pass
    holder.cancel()
    with pytest.raises(asyncio.CancelledError):
        await holder
    assert hosted._queued == 0


def _ready(value):
    async def _coro():
        return value

    return _coro()
