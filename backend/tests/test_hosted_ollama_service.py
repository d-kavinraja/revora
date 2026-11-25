"""Mocked tests for the hosted Ollama service (discovery, gating, concurrency).

No test contacts a real Ollama endpoint, wakes a machine or loads a model.
"""

from __future__ import annotations

import time

import httpx
import pytest

from app.core import config as config_module
from app.services import hosted_ollama_service as hosted
from app.services.hosted_ollama_service import (
    HostedBusyError,
    HostedDisabledError,
    HostedUnavailableError,
    hosted_key,
    parse_hosted_key,
)

BASE = "http://hosted.test:11434"
MODEL = "qwen3:1.7b-q4_K_M"
KEY = hosted_key(MODEL)


@pytest.fixture(autouse=True)
def _configure(monkeypatch):
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_ENABLED", True, raising=False)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_BASE_URL", BASE, raising=False)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_TOKEN", None, raising=False)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_URL_TOKEN", None, raising=False)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_WAKE_ENABLED", False, raising=False)
    monkeypatch.setattr(config_module.settings, "REDIS_URL", None, raising=False)
    hosted.reset_runtime_state()
    hosted._load_ops.clear()
    yield
    hosted._load_ops.clear()
    hosted.reset_runtime_state()


def _mock_discovery(monkeypatch, *, loaded=(MODEL,), tags=None, show=None):
    """Simulate /api/ps (runtime), /api/tags (catalog) and /api/show (metadata)."""
    tags = tags if tags is not None else list(loaded) + ["llama3:8b"]
    show = show or {}

    async def fake_fetch(path, *, timeout):
        if path == "/api/ps":
            return {"models": [{"name": n} for n in loaded]}, None
        if path == "/api/tags":
            return {"models": [{"name": n, "details": {"family": "qwen3"}} for n in tags]}, None
        if path == "/api/version":
            return {"version": "0.40.17"}, None
        return None, "unexpected path"

    async def fake_post(path, payload, *, timeout):
        if path == "/api/show":
            return show.get(payload.get("model"))
        return None

    monkeypatch.setattr(hosted, "_fetch_json", fake_fetch)
    monkeypatch.setattr(hosted, "_post_json", fake_post)


def test_parse_hosted_key_roundtrip():
    assert parse_hosted_key(KEY) == MODEL
    assert parse_hosted_key("qwen3.8-27b") is None


def test_parse_hosted_key_rejects_malformed():
    with pytest.raises(HostedUnavailableError):
        parse_hosted_key("hosted-ollama:../etc/passwd")
    with pytest.raises(HostedUnavailableError):
        parse_hosted_key("hosted-ollama:")


async def test_discovery_exposes_installed_and_loaded_models(monkeypatch):
    # /api/tags lists an extra installed-but-unloaded model; it must appear as
    # installed but NOT loaded (runtime-only selection still holds).
    _mock_discovery(monkeypatch, loaded=(MODEL,), tags=[MODEL, "llama3:8b"])
    snapshot = await hosted.get_snapshot(None, force=True)
    assert snapshot.reachable is True
    assert {m.model for m in snapshot.models} == {MODEL, "llama3:8b"}
    loaded = {m.model for m in snapshot.models if m.loaded}
    installed = {m.model for m in snapshot.models if m.installed}
    assert loaded == {MODEL}
    assert installed == {MODEL, "llama3:8b"}
    unloaded = [m for m in snapshot.models if m.model == "llama3:8b"][0]
    assert unloaded.loaded is False
    assert unloaded.ready is False
    assert unloaded.readiness == "unloaded"
    assert unloaded.admin_loadable is True


async def test_discovery_enriches_context_and_capabilities(monkeypatch):
    _mock_discovery(
        monkeypatch,
        loaded=(MODEL,),
        tags=[MODEL],
        show={MODEL: {"model_info": {"qwen3.context_length": 40960}, "capabilities": ["completion", "tools"]}},
    )
    snapshot = await hosted.get_snapshot(None, force=True)
    model = snapshot.models[0]
    assert model.context_window == 40960
    assert model.vision is False
    assert "qwen3" in model.tags


async def test_ensure_model_ready_returns_loaded_model(monkeypatch):
    _mock_discovery(monkeypatch)
    model = await hosted.ensure_model_ready(None, KEY)
    assert model.key == KEY


async def test_ensure_model_ready_rejects_unloaded_model(monkeypatch):
    _mock_discovery(monkeypatch, loaded=(MODEL,))
    with pytest.raises(HostedUnavailableError) as exc:
        await hosted.ensure_model_ready(None, hosted_key("llama3:8b"))
    assert exc.value.definitive is True
    assert exc.value.reason_code == "model_not_loaded"


async def test_ensure_model_ready_never_substitutes(monkeypatch):
    _mock_discovery(monkeypatch, loaded=())  # nothing loaded
    with pytest.raises(hosted.HostedNotFoundError):
        await hosted.ensure_model_ready(None, KEY)


async def test_disabled_env_blocks_selection(monkeypatch):
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_ENABLED", False, raising=False)
    _mock_discovery(monkeypatch)
    with pytest.raises(HostedDisabledError):
        await hosted.ensure_model_ready(None, KEY)


async def test_admin_selection_disabled_blocks(monkeypatch, test_db):
    _mock_discovery(monkeypatch)
    await hosted.set_selection(test_db, enabled=False, admin_id=None)
    await test_db.commit()
    with pytest.raises(HostedDisabledError):
        await hosted.ensure_model_ready(test_db, KEY)
    # Re-enabling restores access without touching kLLM.
    await hosted.set_selection(test_db, enabled=True, admin_id=None)
    await test_db.commit()
    model = await hosted.ensure_model_ready(test_db, KEY)
    assert model.key == KEY


async def test_concurrency_per_model_cap_and_queue_timeout(monkeypatch):
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_MAX_CONCURRENT_REQUESTS", 4, raising=False)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_MAX_CONCURRENT_REQUESTS_PER_MODEL", 1, raising=False)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_QUEUE_TIMEOUT_S", 0.05, raising=False)
    hosted.reset_runtime_state()

    async def scenario():
        async with hosted.permit(MODEL):
            assert hosted.concurrency_status()["inflight"] == 1
            with pytest.raises(HostedBusyError):
                async with hosted.permit(MODEL):
                    pass  # never acquired

    await scenario()
    status = hosted.concurrency_status()
    assert status["inflight"] == 0
    assert status["queued"] == 0


async def test_concurrency_permit_released_on_error(monkeypatch):
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_MAX_CONCURRENT_REQUESTS_PER_MODEL", 1, raising=False)
    hosted.reset_runtime_state()

    async def scenario():
        with pytest.raises(RuntimeError):
            async with hosted.permit(MODEL):
                raise RuntimeError("boom")

    await scenario()
    assert hosted.concurrency_status()["inflight"] == 0


async def test_global_cap_allows_different_models(monkeypatch):
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_MAX_CONCURRENT_REQUESTS", 2, raising=False)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_MAX_CONCURRENT_REQUESTS_PER_MODEL", 1, raising=False)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_QUEUE_TIMEOUT_S", 0.05, raising=False)
    hosted.reset_runtime_state()

    async def scenario():
        async with hosted.permit(MODEL):
            async with hosted.permit("llama3:8b"):
                assert hosted.concurrency_status()["inflight"] == 2

    await scenario()
    assert hosted.concurrency_status()["inflight"] == 0


def test_ssrf_rejects_metadata_address(monkeypatch):
    monkeypatch.setattr(
        config_module.settings, "REVORA_HOSTED_OLLAMA_BASE_URL", "http://169.254.169.254", raising=False
    )
    assert hosted.is_configured() is False


def test_ssrf_rejects_embedded_credentials(monkeypatch):
    monkeypatch.setattr(
        config_module.settings, "REVORA_HOSTED_OLLAMA_BASE_URL", "http://user:pass@host:11434", raising=False
    )
    assert hosted.is_configured() is False


def test_allows_loopback_private_transport(monkeypatch):
    monkeypatch.setattr(
        config_module.settings, "REVORA_HOSTED_OLLAMA_BASE_URL", "http://127.0.0.1:11434", raising=False
    )
    assert hosted.is_configured() is True


async def test_redis_outage_falls_back_and_releases_local_permit(monkeypatch):
    """A Redis failure mid-acquire must not leak the in-process permit."""
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_MAX_CONCURRENT_REQUESTS_PER_MODEL", 1, raising=False)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_QUEUE_TIMEOUT_S", 0.05, raising=False)
    hosted.reset_runtime_state()

    class _BrokenRedis:
        async def eval(self, *a, **k):
            raise RuntimeError("redis down")

        async def zrem(self, *a, **k):
            return 0

    async def fake_mode():
        return "redis"

    async def fake_redis():
        return _BrokenRedis()

    monkeypatch.setattr(hosted, "_resolve_gate_mode", fake_mode)
    monkeypatch.setattr(hosted, "_get_redis", fake_redis)

    async def scenario():
        async with hosted.permit(MODEL):
            assert hosted.concurrency_status()["inflight"] == 1
        # Permit must be fully released so the next request can acquire it.
        async with hosted.permit(MODEL):
            assert hosted.concurrency_status()["inflight"] == 1

    await scenario()
    assert hosted.concurrency_status()["inflight"] == 0


async def test_installed_not_loaded_is_visible_but_not_loaded(monkeypatch):
    _mock_discovery(monkeypatch, loaded=(), tags=[MODEL])
    snapshot = await hosted.get_snapshot(None, force=True)
    assert [m.model for m in snapshot.models] == [MODEL]
    m = snapshot.models[0]
    assert m.installed is True
    assert m.loaded is False
    assert m.ready is False
    assert m.readiness == "unloaded"
    assert m.admin_loadable is True


async def test_runtime_unknown_when_ps_fails(monkeypatch):
    async def fake_fetch(path, *, timeout):
        if path == "/api/ps":
            return None, "Hosted Ollama is unreachable."
        if path == "/api/tags":
            return {"models": [{"name": MODEL, "details": {"context_length": 40960}}]}, None
        if path == "/api/version":
            return {"version": "0.40.17"}, None
        return None, "unexpected"

    async def fake_post(path, payload, *, timeout):
        return None

    monkeypatch.setattr(hosted, "_fetch_json", fake_fetch)
    monkeypatch.setattr(hosted, "_post_json", fake_post)
    snapshot = await hosted.get_snapshot(None, force=True)
    assert snapshot.reachable is True
    assert snapshot.runtime_unknown is True
    assert snapshot.partial is True
    assert len(snapshot.models) == 1
    m = snapshot.models[0]
    assert m.installed is True
    assert m.loaded is False
    assert m.readiness == "unknown"
    assert m.ready is False


async def test_failed_discovery_serves_stale_without_marking_unloaded(monkeypatch):
    _mock_discovery(monkeypatch, loaded=(MODEL,), tags=[MODEL])
    first = await hosted.get_snapshot(None, force=True)
    assert first.reachable is True

    async def fail_fetch(path, *, timeout):
        return None, "Hosted Ollama is unreachable."

    async def fail_post(path, payload, *, timeout):
        return None

    monkeypatch.setattr(hosted, "_fetch_json", fail_fetch)
    monkeypatch.setattr(hosted, "_post_json", fail_post)
    second = await hosted.get_snapshot(None, force=True)
    assert second.reachable is True
    assert second.stale is True
    assert second.models == []
    assert second.error is not None


async def test_ensure_model_ready_rejects_installed_not_loaded(monkeypatch):
    _mock_discovery(monkeypatch, loaded=(), tags=[MODEL])
    with pytest.raises(hosted.HostedUnavailableError) as exc:
        await hosted.ensure_model_ready(None, KEY)
    assert exc.value.reason_code == "model_not_loaded"
    assert exc.value.definitive is True


async def test_ensure_model_ready_rejects_runtime_unknown(monkeypatch):
    async def fake_fetch(path, *, timeout):
        if path == "/api/ps":
            return None, "Hosted Ollama is unreachable."
        if path == "/api/tags":
            return {"models": [{"name": MODEL, "details": {}}]}, None
        if path == "/api/version":
            return {"version": "0.40.17"}, None
        return None, "unexpected"

    async def fake_post(path, payload, *, timeout):
        return None

    monkeypatch.setattr(hosted, "_fetch_json", fake_fetch)
    monkeypatch.setattr(hosted, "_post_json", fake_post)
    with pytest.raises(hosted.HostedUnavailableError) as exc:
        await hosted.ensure_model_ready(None, KEY)
    assert exc.value.reason_code == "runtime_unknown"


async def test_ensure_model_ready_rejects_unknown_model(monkeypatch):
    _mock_discovery(monkeypatch, loaded=(), tags=())
    with pytest.raises(hosted.HostedNotFoundError):
        await hosted.ensure_model_ready(None, KEY)


async def test_snapshot_reports_provider_state_and_verification_evidence(monkeypatch):
    _mock_discovery(monkeypatch, loaded=(MODEL,), tags=[MODEL])
    snapshot = await hosted.get_snapshot(None, force=True)
    assert (snapshot.state, snapshot.reason) == ("ready", "ready")
    assert snapshot.discovery_ok is True
    assert snapshot.last_success_at is not None
    assert snapshot.cooldown_until is None
    row = snapshot.models[0]
    assert row.last_verified_at is not None
    assert row.partial is False
    assert row.load_state is None
    assert row.as_dict()["last_verified_at"] == row.last_verified_at


async def test_snapshot_state_marks_runtime_unknown_as_verifying(monkeypatch):
    async def fake_fetch(path, *, timeout):
        if path == "/api/ps":
            return None, "Hosted Ollama is unreachable."
        if path == "/api/tags":
            return {"models": [{"name": MODEL, "details": {}}]}, None
        if path == "/api/version":
            return {"version": "0.40.17"}, None
        return None, "unexpected"

    async def fake_post(path, payload, *, timeout):
        return None

    monkeypatch.setattr(hosted, "_fetch_json", fake_fetch)
    monkeypatch.setattr(hosted, "_post_json", fake_post)
    snapshot = await hosted.get_snapshot(None, force=True)
    assert snapshot.state == "verifying"
    assert snapshot.reason == "runtime_unknown"
    assert snapshot.models[0].partial is True


async def test_loaded_runner_context_length_overrides_catalog_metadata(monkeypatch):
    """The context length the loaded runner reports is authoritative."""

    async def fake_fetch(path, *, timeout):
        if path == "/api/ps":
            return {"models": [{"name": MODEL, "context_length": 8192}]}, None
        if path == "/api/tags":
            return {"models": [{"name": MODEL, "details": {"context_length": 40960}}]}, None
        if path == "/api/version":
            return {"version": "0.40.17"}, None
        return None, "unexpected"

    async def fake_post(path, payload, *, timeout):
        return None

    monkeypatch.setattr(hosted, "_fetch_json", fake_fetch)
    monkeypatch.setattr(hosted, "_post_json", fake_post)

    snapshot = await hosted.get_snapshot(None, force=True)
    assert snapshot.models[0].context_window == 8192
    assert snapshot.models[0].ready is True


async def test_installed_context_is_kept_when_runner_reports_none(monkeypatch):
    _mock_discovery(monkeypatch, loaded=(), tags=[MODEL])
    snapshot = await hosted.get_snapshot(None, force=True)
    assert snapshot.models[0].context_window is None


async def test_tracked_load_operation_reports_verifying(monkeypatch):
    _mock_discovery(monkeypatch, loaded=(), tags=[MODEL])
    hosted._load_ops[MODEL] = {"state": "verifying", "started": time.monotonic()}
    snapshot = await hosted.get_snapshot(None, force=True)
    model = snapshot.models[0]
    assert model.readiness == "verifying"
    assert model.load_state == "verifying"
    assert model.ready is False
    verified = model.as_dict()
    assert verified["load_state"] == "verifying"
    assert verified["ready"] is False


# --- gateway redirect handling ----------------------------------------------


def test_same_origin_relative_redirect_is_resolved_to_the_configured_origin():
    response = httpx.Response(303, headers={"location": "/gw/login"})
    assert hosted.same_origin_redirect_target(response) == f"{BASE}/gw/login"


def test_same_origin_absolute_redirect_is_allowed():
    response = httpx.Response(302, headers={"location": f"{BASE}/gw/login"})
    assert hosted.same_origin_redirect_target(response) == f"{BASE}/gw/login"


@pytest.mark.parametrize(
    "location",
    [
        "http://evil.test/gw/login",
        "https://gateway.example.com/steal",
        "http://hosted.test:9999/gw/login",
        "ftp://hosted.test/gw/login",
        "//evil.test/gw/login",
    ],
)
def test_cross_origin_or_unsupported_redirect_is_rejected(location):
    response = httpx.Response(303, headers={"location": location})
    with pytest.raises(hosted.HostedRedirectError) as exc:
        hosted.same_origin_redirect_target(response)
    assert exc.value.reason_code == "hosted_redirect"
    # No configuration value, origin or token is echoed back.
    assert "hosted.test:11434" not in exc.value.message
    assert "evil.test" not in exc.value.message


def test_non_redirect_response_is_not_treated_as_one():
    assert hosted.same_origin_redirect_target(httpx.Response(200)) is None
    assert hosted.same_origin_redirect_target(httpx.Response(303)) is None
