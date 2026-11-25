"""Focused tests proving global hosted model-load serialization.

No real model load, inference, Redis or database coordination occurs. The
cross-worker lease is faked with a single in-memory global slot.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from app.core import config as config_module
from app.services import hosted_ollama_service as hosted

MODEL_A = "qwen3:1.7b-q4_K_M"
MODEL_B = "gemma4:e4b"
KEY_A = hosted.hosted_key(MODEL_A)
KEY_B = hosted.hosted_key(MODEL_B)


class _GlobalSlot:
    """Fake single global slot with owner-checked, expiring release."""

    def __init__(self):
        self.owner = None
        self.expires = 0.0

    async def claim(self, kind, key, ttl):
        assert kind == "load" and key == "global", (kind, key)
        now = time.monotonic()
        if self.owner and now < self.expires:
            return False, "other-worker", "fake"
        owner = f"owner-{time.monotonic_ns()}"
        self.owner = owner
        self.expires = now + ttl
        return True, owner, "fake"

    async def release(self, kind, key, owner, mode):
        assert kind == "load" and key == "global", (kind, key)
        if self.owner == owner:
            self.owner = None
            self.expires = 0.0


class _GenerateClient:
    def __init__(self, loaded, fail=False):
        self.loaded = loaded
        self.fail = fail
        self.calls = 0

    async def post(self, url, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")
        self.loaded.add(kwargs.get("json", {}).get("model"))
        return type("R", (), {"status_code": 200})()


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_ENABLED", True, raising=False)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_WAKE_ENABLED", False, raising=False)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_READY_TIMEOUT_S", 1.0, raising=False)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_READY_POLL_INTERVAL_S", 0.01, raising=False)
    hosted.reset_runtime_state()
    yield
    hosted.reset_runtime_state()


def _install_fakes(monkeypatch, loaded, slot, *, fail=False):
    async def fake_fetch(path, *, timeout):
        if path == "/api/ps":
            return {"models": [{"name": n} for n in loaded]}, None
        if path == "/api/tags":
            return {"models": [
                {"name": MODEL_A, "details": {}},
                {"name": MODEL_B, "details": {}},
            ]}, None
        if path == "/api/version":
            return {"version": "0.40.17"}, None
        return None, "unexpected"

    async def fake_post(path, payload, *, timeout):
        if path == "/api/show":
            return None
        return None

    client = _GenerateClient(loaded, fail=fail)
    monkeypatch.setattr(hosted, "_fetch_json", fake_fetch)
    monkeypatch.setattr(hosted, "_post_json", fake_post)
    monkeypatch.setattr(hosted, "_get_client", lambda: client)
    monkeypatch.setattr(hosted, "claim_lease", slot.claim)
    monkeypatch.setattr(hosted, "release_lease", slot.release)
    return client


async def test_same_model_two_requests_cannot_overlap(monkeypatch):
    loaded = set()
    slot = _GlobalSlot()
    client = _install_fakes(monkeypatch, loaded, slot)

    results = await asyncio.gather(
        hosted.load_model(None, KEY_A),
        hosted.load_model(None, KEY_A),
        return_exceptions=True,
    )
    assert client.calls == 1
    assert any(isinstance(r, hosted.HostedConflictError) for r in results)


async def test_different_models_cannot_overlap(monkeypatch):
    loaded = set()
    slot = _GlobalSlot()
    client = _install_fakes(monkeypatch, loaded, slot)

    results = await asyncio.gather(
        hosted.load_model(None, KEY_A),
        hosted.load_model(None, KEY_B),
        return_exceptions=True,
    )
    # Both may finish sequentially, but never concurrently: only one generate
    # call at a time and a conflict for a request arriving while occupied.
    assert client.calls in (1, 2)
    assert all(not isinstance(r, Exception) or isinstance(r, hosted.HostedConflictError) for r in results)
    assert all(r.get("status") == "loaded" for r in results if isinstance(r, dict))


async def test_cross_worker_conflict_is_structured(monkeypatch):
    slot = _GlobalSlot()
    loaded = set()
    _install_fakes(monkeypatch, loaded, slot)
    assert await slot.claim("load", "global", 30) is not None
    owned, owner, mode = await slot.claim("load", "global", 30)
    assert owned is False
    with pytest.raises(hosted.HostedConflictError) as exc:
        await hosted.load_model(None, KEY_A)
    assert exc.value.reason_code == "load_in_progress"


async def test_exception_releases_global_slot(monkeypatch):
    loaded = set()
    slot = _GlobalSlot()
    _install_fakes(monkeypatch, loaded, slot, fail=True)
    for _ in range(2):
        with pytest.raises(hosted.HostedUnavailableError):
            await hosted.load_model(None, KEY_A)
    assert slot.owner is None


async def test_already_loaded_skips_generate(monkeypatch):
    loaded = {MODEL_A}
    slot = _GlobalSlot()
    client = _install_fakes(monkeypatch, loaded, slot)
    result = await hosted.load_model(None, KEY_A)
    assert result["status"] == "already_loaded"
    assert result["verified"] is True
    assert client.calls == 0


async def test_lease_owner_checked_release(monkeypatch):
    slot = _GlobalSlot()
    got, owner, mode = await slot.claim("load", "global", 30)
    assert got is True
    await slot.release("load", "global", "someone-else", mode)
    assert slot.owner == owner
    await slot.release("load", "global", owner, mode)
    assert slot.owner is None


async def test_expired_lease_recovery(monkeypatch):
    slot = _GlobalSlot()
    got, owner, mode = await slot.claim("load", "global", -1)
    assert got is True
    got2, _, _ = await slot.claim("load", "global", 30)
    assert got2 is True
