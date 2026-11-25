"""Mocked tests for hosted-model routing through the Chat API and catalog.

No test contacts a real Ollama endpoint or performs real inference.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import httpx

from app.ai.llm import llm_service
from app.core import config as config_module
from app.services import hosted_ollama_service as hosted
from app.services import kllm_service
from app.services.chat_service import context_fit_budget, reset_chat_runtime_state
from app.services.hosted_ollama_service import HostedModel, hosted_key
from app.services.kllm_service import KllmModel

MODEL = "qwen3:1.7b-q4_K_M"
KEY = hosted_key(MODEL)
BASE = "http://hosted.test:11434"


@pytest.fixture(autouse=True)
def _reset():
    reset_chat_runtime_state()
    hosted.reset_runtime_state()
    yield
    reset_chat_runtime_state()
    hosted.reset_runtime_state()


@pytest.fixture(autouse=True)
def _patch_chat_db(test_db, monkeypatch):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _cm():
        yield test_db

    monkeypatch.setattr("app.api.v1.endpoints.chat.AsyncSessionLocal", _cm)


@pytest.fixture(autouse=True)
def _configure(monkeypatch):
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_ENABLED", True, raising=False)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_BASE_URL", BASE, raising=False)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_URL_TOKEN", None, raising=False)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_WAKE_ENABLED", False, raising=False)
    monkeypatch.setattr(config_module.settings, "REDIS_URL", None, raising=False)


def _payload(**overrides):
    payload = {"model": KEY, "messages": [{"role": "user", "content": "Hello"}], "stream": False}
    payload.update(overrides)
    return payload


def _parse_sse(body: str) -> list[dict]:
    events = []
    for frame in body.split("\n\n"):
        frame = frame.strip()
        if frame.startswith("data:"):
            events.append(json.loads(frame[len("data:"):].strip()))
    return events


def _ready_hosted_model() -> HostedModel:
    return HostedModel(key=KEY, model=MODEL, context_window=40960)


async def test_hosted_non_streaming_routes_to_hosted_client(client, monkeypatch):
    captured = {}

    async def fake_ensure(_db, key):
        assert key == KEY
        return _ready_hosted_model()

    async def fake_complete(model, messages, **kwargs):
        captured["model"] = model
        return "hosted reply", 10, 20

    async def never_kllm(*_a, **_k):
        raise AssertionError("kLLM client must not be used for a hosted model")

    monkeypatch.setattr(hosted, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(llm_service, "complete_hosted", fake_complete)
    monkeypatch.setattr(llm_service, "complete_managed", never_kllm)

    response = client.post("/api/v1/chat/completions", json=_payload())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model"] == KEY
    assert body["content"] == "hosted reply"
    # The transport receives the bare Ollama name, not the namespaced key.
    assert captured["model"] == MODEL


async def test_hosted_streaming_uses_same_sse_contract(client, monkeypatch):
    async def fake_ensure(_db, _key):
        return _ready_hosted_model()

    async def fake_stream(model, messages, **kwargs):
        assert model == MODEL
        yield "Hel"
        yield "lo"

    monkeypatch.setattr(hosted, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(llm_service, "stream_hosted_completion", fake_stream)

    with client.stream("POST", "/api/v1/chat/completions", json=_payload(stream=True)) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        body = "".join(response.iter_text())

    events = _parse_sse(body)
    assert {"type": "delta", "content": "Hel"} in events
    assert {"type": "delta", "content": "lo"} in events
    assert events[-1]["type"] == "done"


async def test_hosted_disabled_env_returns_safe_503(client, monkeypatch):
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_ENABLED", False, raising=False)
    response = client.post("/api/v1/chat/completions", json=_payload())
    assert response.status_code == 503
    assert response.json()["detail"] == hosted.DISABLED_MESSAGE


async def test_hosted_admin_selection_disabled_returns_503(client, test_db, monkeypatch):
    async def fake_fetch(path, *, timeout):
        if path == "/api/ps":
            return {"models": [{"name": MODEL}]}, None
        if path == "/api/tags":
            return {"models": []}, None
        if path == "/api/version":
            return {"version": "0.40.17"}, None
        return None, "unexpected"

    async def fake_post(path, payload, *, timeout):
        return None

    monkeypatch.setattr(hosted, "_fetch_json", fake_fetch)
    monkeypatch.setattr(hosted, "_post_json", fake_post)
    await hosted.set_selection(test_db, enabled=False, admin_id=None)
    await test_db.commit()

    response = client.post("/api/v1/chat/completions", json=_payload())
    assert response.status_code == 503
    assert "disabled" in response.json()["detail"].lower()


async def test_catalog_merges_kllm_and_hosted(client, monkeypatch):
    kllm_model = KllmModel(
        key="qwen3.8-27b", status="loaded", loaded=True, ready=True,
        context_window=131072, vision=False, readiness="ready", reason_code="ready",
    )
    kllm_snapshot = SimpleNamespace(
        enabled=True, configured=True, reachable=True, stale=False, error=None,
        models=[kllm_model], generated_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )
    hosted_snapshot = hosted.HostedSnapshot(
        enabled=True, configured=True, reachable=True, stale=False,
        generated_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        age_seconds=0.0, error=None, models=[_ready_hosted_model()],
        selection_enabled=True, wake_enabled=False, waking=False, version="0.40.17",
        concurrency=hosted.concurrency_status(),
    )

    async def fake_kllm_snapshot(_db, **_k):
        return kllm_snapshot

    async def fake_hosted_snapshot(_db, **_k):
        return hosted_snapshot

    monkeypatch.setattr(kllm_service, "get_snapshot", fake_kllm_snapshot)
    monkeypatch.setattr(hosted, "get_snapshot", fake_hosted_snapshot)

    response = client.get("/api/v1/chat/models")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is True
    assert body["reachable"] is True
    keys = {m["key"]: m for m in body["models"]}
    assert "qwen3.8-27b" in keys
    assert KEY in keys
    assert keys[KEY]["provider"] == "hosted-ollama"
    assert keys[KEY]["category"] == "hosted"
    assert keys["qwen3.8-27b"]["provider"] == "kllm"
    providers = {p["provider"] for p in body["providers"]}
    assert providers == {"kllm", "hosted-ollama"}


async def test_keep_alive_validation_accepts_ollama_formats():
    """The keep_alive forms Ollama documents are all accepted."""
    from app.core.config import keep_alive_is_valid, keep_alive_payload_value

    for value in ("5m", "30s", "1h", "-1"):
        assert keep_alive_is_valid(value) is True
    assert keep_alive_payload_value("5m") == "5m"
    assert keep_alive_payload_value("-1") == -1
    assert keep_alive_is_valid("5 minutes") is False


async def test_streaming_upstream_400_reaches_sse_with_classified_code(client, monkeypatch):
    """A classified 400 survives client -> SSE -> endpoint without remapping."""

    async def fake_ensure(_db, _key):
        return _ready_hosted_model()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            text='{"error":{"message":"invalid request","type":"invalid_request_error"}}',
            headers={"content-type": "application/json"},
        )

    gateway_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(hosted, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(hosted, "_get_client", lambda: gateway_client)

    with client.stream(
        "POST", "/api/v1/chat/completions", json=_payload(stream=True)
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    errors = [event for event in _parse_sse(body) if event.get("type") == "error"]
    assert errors, body
    assert errors[0]["code"] == "upstream_rejected_unclassified"
    assert "could not classify" in errors[0]["message"]
    assert "Try shortening the conversation" not in errors[0]["message"]


async def test_non_streaming_upstream_400_returns_structured_detail(client, monkeypatch):
    async def fake_ensure(_db, _key):
        return _ready_hosted_model()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            text='{"error":{"message":"invalid request","type":"invalid_request_error"}}',
            headers={"content-type": "application/json"},
        )

    gateway_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(hosted, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(hosted, "_get_client", lambda: gateway_client)

    response = client.post("/api/v1/chat/completions", json=_payload(stream=False))

    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "upstream_rejected_unclassified"
    assert "could not classify" in detail["message"]
    assert "Try shortening the conversation" not in detail["message"]


async def test_catalog_requires_auth(anon_client):
    response = anon_client.get("/api/v1/chat/models")
    assert response.status_code == 401


async def test_failed_streaming_request_releases_the_single_flight_lease(client, monkeypatch):
    """A streaming request that fails before SSE starts must not lock the user out.

    enforce_chat_limits() takes the lease before validation runs. If a streaming
    request raises there (model not ready, unreachable runtime), the lease must
    still be released; otherwise the next message is rejected with
    "A response is already being generated" for the whole lease TTL.
    """

    async def unreachable(_db, _key):
        raise hosted.HostedUnavailableError("Hosted Ollama is unreachable.")

    monkeypatch.setattr(hosted, "ensure_model_ready", unreachable)

    first = client.post("/api/v1/chat/completions", json=_payload(stream=True))
    assert first.status_code != 429, first.text

    second = client.post("/api/v1/chat/completions", json=_payload(stream=True))
    assert second.status_code != 429, second.text
    assert "already being generated" not in second.text


async def test_streaming_upstream_error_releases_the_single_flight_lease(client, monkeypatch):
    """After an upstream 400 on the SSE path, the next message is not blocked."""

    async def fake_ensure(_db, _key):
        return _ready_hosted_model()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="", headers={"content-type": "application/json"})

    gateway_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(hosted, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(hosted, "_get_client", lambda: gateway_client)

    with client.stream(
        "POST", "/api/v1/chat/completions", json=_payload(stream=True)
    ) as response:
        body = "".join(response.iter_text())
    assert "upstream_rejected_unclassified" in body

    retry = client.post("/api/v1/chat/completions", json=_payload(stream=False))
    assert retry.status_code != 429, retry.text
    assert retry.status_code == 400, retry.text


async def test_catalog_exposes_installed_but_unloaded_as_disabled(client, monkeypatch):
    """An installed-but-unloaded hosted model is visible but never selectable."""
    installed_only = hosted.HostedModel(
        key=hosted_key("llama3:8b"),
        model="llama3:8b",
        installed=True,
        loaded=False,
        status="installed",
        ready=False,
        readiness="unloaded",
        reason_code="model_not_loaded",
        admin_loadable=True,
        last_verified_at="2024-01-01T00:00:00+00:00",
    )
    hosted_snapshot = hosted.HostedSnapshot(
        enabled=True, configured=True, reachable=True, stale=False,
        generated_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        age_seconds=0.0, error=None, models=[installed_only],
        selection_enabled=True, wake_enabled=False, waking=False, version="0.40.17",
        concurrency=hosted.concurrency_status(), state="ready", reason="ready",
        discovery_ok=True, last_success_at="2024-01-01T00:00:00+00:00",
    )
    kllm_snapshot = SimpleNamespace(
        enabled=False, configured=False, reachable=False, stale=False, error=None,
        models=[], generated_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )

    async def fake_kllm_snapshot(_db, **_k):
        return kllm_snapshot

    async def fake_hosted_snapshot(_db, **_k):
        return hosted_snapshot

    monkeypatch.setattr(kllm_service, "get_snapshot", fake_kllm_snapshot)
    monkeypatch.setattr(hosted, "get_snapshot", fake_hosted_snapshot)

    response = client.get("/api/v1/chat/models")
    assert response.status_code == 200, response.text
    body = response.json()
    row = next(m for m in body["models"] if m["key"] == hosted_key("llama3:8b"))
    assert row["installed"] is True
    assert row["ready"] is False
    assert row["readiness"] == "unloaded"
    assert row["admin_loadable"] is True
    assert row["last_verified_at"] == "2024-01-01T00:00:00+00:00"
    hosted_provider = next(p for p in body["providers"] if p["provider"] == "hosted-ollama")
    assert hosted_provider["state"] == "ready"
    assert hosted_provider["reason"] == "ready"
    assert hosted_provider["discovery_ok"] is True


async def test_provider_mismatch_is_rejected_before_readiness(client, monkeypatch):
    called = {"hosted": False, "kllm": False}

    async def fake_hosted_ensure(_db, _key):
        called["hosted"] = True
        return _ready_hosted_model()

    async def fake_kllm_ensure(_db, _key):
        called["kllm"] = True
        return _ready_hosted_model()

    monkeypatch.setattr(hosted, "ensure_model_ready", fake_hosted_ensure)
    monkeypatch.setattr(kllm_service, "ensure_model_ready", fake_kllm_ensure)

    response = client.post(
        "/api/v1/chat/completions", json=_payload(provider="kllm")
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["detail"]["code"] == "provider_mismatch"
    assert called == {"hosted": False, "kllm": False}


async def test_provider_assertion_accepts_matching_provider(client, monkeypatch):
    async def fake_ensure(_db, _key):
        return _ready_hosted_model()

    async def fake_complete(_model, _messages, **_kwargs):
        return "hosted reply", 1, 1

    monkeypatch.setattr(hosted, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(llm_service, "complete_hosted", fake_complete)

    response = client.post(
        "/api/v1/chat/completions", json=_payload(provider="hosted-ollama")
    )
    assert response.status_code == 200, response.text


async def test_hosted_prompt_is_fitted_to_runtime_window(client, monkeypatch):
    """A long hosted conversation is fitted locally before it is sent upstream."""
    captured = {}

    async def fake_ensure(_db, _key):
        return HostedModel(key=KEY, model=MODEL, context_window=8192, ready=True)

    async def fake_stream(_model, messages, **_kwargs):
        captured["messages"] = messages
        yield "ok"

    monkeypatch.setattr(hosted, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(llm_service, "stream_hosted_completion", fake_stream)

    messages = []
    for _ in range(10):
        messages.append({"role": "user", "content": "u" * 4000})
        messages.append({"role": "assistant", "content": "a" * 4000})
    messages.append({"role": "user", "content": "final"})

    with client.stream(
        "POST",
        "/api/v1/chat/completions",
        json=_payload(stream=True, messages=messages),
    ) as response:
        assert response.status_code == 200
        "".join(response.iter_text())

    sent = captured["messages"]
    assert sent[-1] == {"role": "user", "content": "final"}
    _, budget_chars = context_fit_budget(8192, None)
    total_chars = sum(len(m["content"]) for m in sent)
    assert total_chars <= budget_chars
    # Strict alternation for the hosted provider.
    roles = [m["role"] for m in sent]
    assert roles[0] == "user"
    assert all(a != b for a, b in zip(roles, roles[1:]))


async def test_hosted_large_window_keeps_the_whole_conversation(client, monkeypatch):
    """A hosted model with a large window receives more than 20 turns."""
    captured = {}

    async def fake_ensure(_db, _key):
        return HostedModel(key=KEY, model=MODEL, context_window=131072, ready=True)

    async def fake_stream(_model, messages, **_kwargs):
        captured["messages"] = messages
        yield "ok"

    monkeypatch.setattr(hosted, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(llm_service, "stream_hosted_completion", fake_stream)

    messages = []
    for index in range(30):
        messages.append({"role": "user", "content": f"u{index} " + ("x" * 100)})
        messages.append({"role": "assistant", "content": f"a{index} " + ("y" * 100)})
    messages.append({"role": "user", "content": "final"})

    with client.stream(
        "POST",
        "/api/v1/chat/completions",
        json=_payload(stream=True, messages=messages),
    ) as response:
        assert response.status_code == 200
        "".join(response.iter_text())

    sent = captured["messages"]
    assert len(sent) == len(messages)
    assert sent[0]["role"] == "user"
    assert sent[-1] == {"role": "user", "content": "final"}
    _, budget_chars = context_fit_budget(131072, None)
    assert sum(len(m["content"]) for m in sent) <= budget_chars


async def test_kllm_context_is_unchanged_by_hosted_fitting(client, monkeypatch):
    """The kLLM pathway keeps its existing (non-strict) context behaviour."""
    captured = {}

    async def fake_ensure(_db, _key):
        return SimpleNamespace(context_window=131072)

    async def fake_stream(_model, messages, **_kwargs):
        captured["messages"] = messages
        yield "ok"

    async def fake_enabled(_db):
        return True

    monkeypatch.setattr(kllm_service, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(kllm_service, "is_enabled", fake_enabled)
    monkeypatch.setattr(llm_service, "stream_managed_completion", fake_stream)

    messages = [
        {"role": "user", "content": "a"},
        {"role": "user", "content": "b"},
    ]
    with client.stream(
        "POST", "/api/v1/chat/completions", json=_payload(model="qwen3.8-27b", stream=True, messages=messages)
    ) as response:
        assert response.status_code == 200
        "".join(response.iter_text())

    assert [m["role"] for m in captured["messages"]] == ["user", "user"]
