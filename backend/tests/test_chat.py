"""Mocked tests for temporary kLLM chat.

No test contacts a real kLLM gateway or performs real inference.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json

import pytest
from sqlalchemy import select

from app.ai import kllm_client
from app.ai.kllm_client import CompletionResult, KllmClientError, StreamMeta
from app.ai.llm import llm_service
from app.core import config as config_module
from app.models.execution import ReviewExecution
from app.models.observability import LLMRequestLog
from app.models.provider import ProviderRegistry
from app.services import kllm_autoload, kllm_service
from app.services import chat_service
from app.services.chat_service import (
    CLIP_MARKER,
    DEFAULT_OUTPUT_TOKENS,
    INCOMPLETE_FINISH_REASON,
    MAX_CONTEXT_CHARS,
    MAX_OUTPUT_TOKENS,
    MAX_REQUEST_MESSAGES,
    MIN_INPUT_TOKENS,
    MIN_OUTPUT_TOKENS,
    OUTPUT_CONTEXT_RESERVE,
    clamp_requested_max_tokens,
    clip_to_budget,
    context_fit_budget,
    estimate_input_tokens,
    max_output_tokens_for_window,
    output_safety_headroom,
    reset_chat_runtime_state,
    resolve_max_tokens,
    stream_chat_sse,
)
from app.services.kllm_service import KllmModel, KllmUnavailableError
from app.services.platform_settings import platform_settings_service

MODEL = "qwen3.8-27b"
SECRET = "sk-THIS-SHOULD-NOT-APPEAR"


@pytest.fixture(autouse=True)
def _reset_chat_runtime():
    reset_chat_runtime_state()
    yield
    reset_chat_runtime_state()


@pytest.fixture(autouse=True)
def _patch_chat_db(test_db, monkeypatch):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _cm():
        yield test_db

    monkeypatch.setattr("app.api.v1.endpoints.chat.AsyncSessionLocal", _cm)
    monkeypatch.setattr("app.services.chat_service.AsyncSessionLocal", _cm, raising=False)


@pytest.fixture
def gateway_enabled(monkeypatch):
    monkeypatch.setattr(config_module.settings, "KLLM_ENABLED", True, raising=False)
    return True


async def _seed_managed_provider(db) -> ProviderRegistry:
    provider = ProviderRegistry(
        name="kllm",
        display_name="kLLM",
        slug="kllm",
        litellm_provider="openai",
        default_model=MODEL,
        api_key_min_length=1,
        is_enabled=True,
        status="available",
        is_managed=True,
        allow_key_addition=False,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return provider


async def _disable_chat_flag(db) -> None:
    await platform_settings_service.set_chat_modes(
        db,
        {"temporary_enabled": False, "persistent_enabled": False},
        expected_version=0,
    )
    await db.commit()


def _ready_model(key: str = MODEL) -> KllmModel:
    return KllmModel(
        key=key,
        status="loaded",
        loaded=True,
        ready=True,
        readiness="ready",
        reason_code="ready",
        context_window=131072,
        vision=False,
        tags=[],
        backend_count=1,
    )


def _chat_payload(**overrides):
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": False,
    }
    payload.update(overrides)
    return payload


def _parse_sse(body: str) -> list[dict]:
    events = []
    for frame in body.split("\n\n"):
        frame = frame.strip()
        if not frame.startswith("data:"):
            continue
        events.append(json.loads(frame[len("data:") :].strip()))
    return events


def test_chat_requires_auth(anon_client):
    response = anon_client.post("/api/v1/chat/completions", json=_chat_payload())
    assert response.status_code == 401


async def test_chat_feature_flag_disabled(client, test_db):
    await _disable_chat_flag(test_db)
    response = client.post("/api/v1/chat/completions", json=_chat_payload())
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "feature_disabled"


async def test_chat_kllm_disabled_returns_safe_message(client, monkeypatch):
    async def disabled(_db):
        return False

    monkeypatch.setattr(kllm_service, "is_enabled", disabled)
    response = client.post("/api/v1/chat/completions", json=_chat_payload())
    assert response.status_code == 503
    assert response.json()["detail"] == kllm_service.DISABLED_MESSAGE


async def test_chat_model_not_ready_no_autoload(client, test_db, gateway_enabled, monkeypatch):
    await _seed_managed_provider(test_db)

    async def fake_ensure(_db, model):
        raise KllmUnavailableError(f"Model '{model}' is not ready.", reason_code="model_unloaded")

    async def never_autoload(*_args, **_kwargs):
        raise AssertionError("autoload must not be called")

    monkeypatch.setattr(kllm_service, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(kllm_autoload, "ensure_model_ready_with_autoload", never_autoload)

    response = client.post("/api/v1/chat/completions", json=_chat_payload())
    assert response.status_code == 503
    assert "not ready" in response.json()["detail"].lower()


async def test_chat_validation_rejects_invalid_shapes(client):
    bad_payloads = [
        _chat_payload(messages=[]),
        _chat_payload(messages=[{"role": "assistant", "content": "hi"}]),
        _chat_payload(messages=[{"role": "user", "content": " "}]),
        _chat_payload(messages=[{"role": "system", "content": "nope"}]),
        _chat_payload(messages=[{"role": "user", "content": "a" * 200001}]),
        _chat_payload(messages=[{"role": "user", "content": "ok"}] * (MAX_REQUEST_MESSAGES + 1)),
    ]
    for payload in bad_payloads:
        response = client.post("/api/v1/chat/completions", json=payload)
        assert response.status_code in {400, 422}


async def test_chat_non_streaming_happy_path_no_persistence(client, test_db, gateway_enabled, monkeypatch, caplog):
    await _seed_managed_provider(test_db)
    secret_prompt = f"Reply with {SECRET}"
    secret_reply = f"safe {SECRET}"

    async def fake_ensure(_db, _model):
        return _ready_model()

    async def fake_complete(model, messages, **_kwargs):
        assert model == MODEL
        assert messages[-1]["content"].endswith(SECRET)
        return secret_reply, 12, 34

    async def never_autoload(*_args, **_kwargs):
        raise AssertionError("autoload must not be called")

    monkeypatch.setattr(kllm_service, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(llm_service, "complete_managed", fake_complete)
    monkeypatch.setattr(kllm_autoload, "ensure_model_ready_with_autoload", never_autoload)
    caplog.set_level("INFO")

    before_exec = (await test_db.execute(select(ReviewExecution))).scalars().all()
    before_usage = (await test_db.execute(select(LLMRequestLog))).scalars().all()

    response = client.post(
        "/api/v1/chat/completions",
        json=_chat_payload(messages=[{"role": "user", "content": secret_prompt}]),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model"] == MODEL
    assert body["content"] == secret_reply
    assert body["usage"]["prompt_tokens"] == 12

    after_exec = (await test_db.execute(select(ReviewExecution))).scalars().all()
    after_usage = (await test_db.execute(select(LLMRequestLog))).scalars().all()
    assert len(after_exec) == len(before_exec)
    assert len(after_usage) == len(before_usage)

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert SECRET not in log_text
    assert secret_prompt not in log_text
    assert secret_reply not in log_text


async def test_chat_streaming_happy_path(client, test_db, gateway_enabled, monkeypatch):
    await _seed_managed_provider(test_db)

    async def fake_ensure(_db, _model):
        return _ready_model()

    async def fake_stream(_model, _messages, **_kwargs):
        for part in ["Hel", "lo"]:
            yield part

    monkeypatch.setattr(kllm_service, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(llm_service, "stream_managed_completion", fake_stream)

    with client.stream("POST", "/api/v1/chat/completions", json=_chat_payload(stream=True)) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        # no-transform keeps intermediary compression from buffering SSE frames.
        assert "no-transform" in response.headers["cache-control"]
        body = "".join(response.iter_text())

    events = _parse_sse(body)
    assert {"type": "delta", "content": "Hel"} in events
    assert {"type": "delta", "content": "lo"} in events
    assert events[-1]["type"] == "done"


async def test_chat_context_trimmed_server_side(client, test_db, gateway_enabled, monkeypatch):
    await _seed_managed_provider(test_db)
    seen = {}

    async def fake_ensure(_db, _model):
        return _ready_model()

    async def fake_complete(_model, messages, **_kwargs):
        seen["messages"] = messages
        return "ok", 1, 1

    monkeypatch.setattr(kllm_service, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(llm_service, "complete_managed", fake_complete)

    messages = []
    for i in range(19):
        messages.append({"role": "user", "content": f"u{i} " + ("x" * 2000)})
        messages.append({"role": "assistant", "content": f"a{i} " + ("y" * 2000)})
    messages.append({"role": "user", "content": "final question"})

    assert len(messages) <= MAX_REQUEST_MESSAGES
    response = client.post("/api/v1/chat/completions", json=_chat_payload(messages=messages))
    assert response.status_code == 200, response.text
    sent = seen["messages"]
    # The model reports a 131K window: the whole conversation fits and none of
    # it is silently dropped just because it has more than 20 turns.
    assert len(sent) == len(messages)
    assert sent[-1]["content"] == "final question"
    assert sent[0]["role"] == "user"
    _, budget_chars = context_fit_budget(131_072, None)
    total_chars = sum(len(m["content"]) for m in sent)
    assert total_chars <= budget_chars


async def test_chat_context_is_fitted_for_a_small_window(
    client, test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)
    seen = {}

    async def fake_ensure(_db, _model):
        return dataclasses.replace(_ready_model(), context_window=8192)

    async def fake_complete(_model, messages, **_kwargs):
        seen["messages"] = messages
        return "ok", 1, 1

    monkeypatch.setattr(kllm_service, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(llm_service, "complete_managed", fake_complete)

    messages = []
    for i in range(20):
        messages.append({"role": "user", "content": f"u{i} " + ("x" * 1000)})
        messages.append({"role": "assistant", "content": f"a{i} " + ("y" * 1000)})
    messages.append({"role": "user", "content": "final question"})

    response = client.post("/api/v1/chat/completions", json=_chat_payload(messages=messages))
    assert response.status_code == 200, response.text
    sent = seen["messages"]
    _, budget_chars = context_fit_budget(8192, None)
    assert 0 < len(sent) < len(messages)
    assert sent[-1]["content"] == "final question"
    assert sent[0]["role"] == "user"
    assert sum(len(m["content"]) for m in sent) <= budget_chars


async def test_chat_rate_limit(client, test_db, gateway_enabled, monkeypatch):
    await _seed_managed_provider(test_db)

    async def fake_ensure(_db, _model):
        return _ready_model()

    async def fake_complete(_model, _messages, **_kwargs):
        return "ok", 1, 1

    monkeypatch.setattr(kllm_service, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(llm_service, "complete_managed", fake_complete)

    last = None
    for _ in range(21):
        last = client.post("/api/v1/chat/completions", json=_chat_payload())
    assert last is not None
    assert last.status_code == 429


async def test_chat_safe_gateway_error(client, test_db, gateway_enabled, monkeypatch):
    await _seed_managed_provider(test_db)

    async def fake_ensure(_db, _model):
        return _ready_model()

    async def fake_complete(_model, _messages, **_kwargs):
        raise RuntimeError(f"401 Unauthorized {SECRET} https://internal.example/v1")

    monkeypatch.setattr(kllm_service, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(llm_service, "complete_managed", fake_complete)

    response = client.post("/api/v1/chat/completions", json=_chat_payload())
    assert response.status_code == 503
    detail = str(response.json()["detail"]).lower()
    assert "credentials" in detail or "kllm" in detail
    assert SECRET.lower() not in detail
    assert "internal.example" not in detail


async def test_chat_uses_direct_client_and_not_litellm(
    client, test_db, gateway_enabled, monkeypatch
):
    """The kLLM Chat pathway must use the direct client, never LiteLLM."""
    await _seed_managed_provider(test_db)
    captured = {}

    async def fake_ensure(_db, _model):
        return _ready_model()

    async def fake_complete(model, messages, **kwargs):
        captured.update(model=model, messages=messages, **kwargs)
        return CompletionResult(
            content="direct", prompt_tokens=1, completion_tokens=2
        )

    async def never_autoload(*_args, **_kwargs):
        raise AssertionError("autoload must not be called")

    def no_litellm(*_args, **_kwargs):
        raise AssertionError("LiteLLM must not be used for kLLM chat")

    monkeypatch.setattr(kllm_service, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr("app.ai.llm.acompletion", no_litellm)
    monkeypatch.setattr(kllm_client.kllm_chat_client, "complete", fake_complete)
    monkeypatch.setattr(kllm_autoload, "ensure_model_ready_with_autoload", never_autoload)

    response = client.post(
        "/api/v1/chat/completions",
        json=_chat_payload(reasoning_effort="high", max_tokens=64, temperature=0.2),
    )
    assert response.status_code == 200, response.text
    assert response.json()["content"] == "direct"
    assert captured["model"] == MODEL
    assert captured["reasoning_effort"] == "high"
    assert captured["max_tokens"] == 64
    assert captured["temperature"] == 0.2


async def test_chat_stream_forwards_presence_gated_metadata(
    client, test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)

    async def fake_ensure(_db, _model):
        return _ready_model()

    async def fake_stream(_model, _messages, **kwargs):
        assert kwargs.get("reasoning_effort") == "medium"
        yield kllm_client.ContentDelta("Hel")
        yield StreamMeta("status", {"status": "thinking"})
        yield kllm_client.ContentDelta("lo")
        yield StreamMeta("usage", {"prompt_tokens": 5, "completion_tokens": 2})
        yield StreamMeta("timings", {"gen_tps": 42.0})
        yield StreamMeta("done", {"finish_reason": "stop"})

    monkeypatch.setattr(kllm_service, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(kllm_client.kllm_chat_client, "stream", fake_stream)

    with client.stream(
        "POST",
        "/api/v1/chat/completions",
        json=_chat_payload(stream=True, reasoning_effort="medium"),
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    events = _parse_sse(body)
    assert {"type": "delta", "content": "Hel"} in events
    assert {"type": "delta", "content": "lo"} in events
    assert {"type": "status", "status": "thinking"} in events
    assert {"type": "usage", "prompt_tokens": 5, "completion_tokens": 2} in events
    assert {"type": "timings", "gen_tps": 42.0} in events
    assert events[-1] == {"type": "done", "finish_reason": "stop"}


async def test_chat_stream_maps_client_reason_code(
    client, test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)

    async def fake_ensure(_db, _model):
        return _ready_model()

    async def fake_stream(_model, _messages, **_kwargs):
        raise KllmClientError(
            "kLLM is busy or at capacity. Please try again in a moment.",
            reason_code="kllm_busy",
        )
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(kllm_service, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(kllm_client.kllm_chat_client, "stream", fake_stream)

    with client.stream(
        "POST", "/api/v1/chat/completions", json=_chat_payload(stream=True)
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    events = _parse_sse(body)
    assert events[-1]["type"] == "error"
    assert events[-1]["code"] == "kllm_busy"


async def test_chat_stream_stops_on_client_disconnect(monkeypatch):
    """A disconnected client must stop the upstream stream immediately."""

    class _DisconnectedRequest:
        async def is_disconnected(self) -> bool:
            return True

    async def never_iterated(*_args, **_kwargs):
        raise AssertionError("upstream stream must not be consumed after disconnect")
        yield  # pragma: no cover

    monkeypatch.setattr(llm_service, "stream_managed_completion", never_iterated)

    from app.services.chat_service import stream_chat_sse

    events = [
        event
        async for event in stream_chat_sse(
            _DisconnectedRequest(),
            user_id="disconnect-test",
            model=MODEL,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=8,
            temperature=None,
        )
    ]
    assert events == []


# ---- context-aware output budget -------------------------------------------


def test_estimate_input_tokens_is_a_documented_approximation():
    # Same 3-chars-per-token ratio the fit itself uses, so the estimate can
    # never promise room the fit would refuse to use.
    assert estimate_input_tokens([{"role": "user", "content": "x" * 400}]) == 134
    assert estimate_input_tokens([{"role": "user", "content": "abc"}]) == 1
    assert estimate_input_tokens([{"role": "user", "content": "ab"}]) == 1
    assert estimate_input_tokens([]) == 0


def test_output_budget_uses_context_window_bounded_by_ceiling():
    messages = [{"role": "user", "content": "x" * 400}]
    # An unspecified budget gets the default, not the hard ceiling, even when
    # the window could afford much more.
    assert resolve_max_tokens(None, 131072, messages) == DEFAULT_OUTPUT_TOKENS
    assert resolve_max_tokens(MAX_OUTPUT_TOKENS, 131072, messages) == MAX_OUTPUT_TOKENS
    assert resolve_max_tokens(None, 131072, messages) <= MAX_OUTPUT_TOKENS


def test_output_budget_honours_explicit_override_and_clamps_excess():
    messages = [{"role": "user", "content": "x" * 400}]
    assert resolve_max_tokens(2048, 131072, messages) == 2048
    assert resolve_max_tokens(999_999, 131072, messages) == MAX_OUTPUT_TOKENS
    assert resolve_max_tokens(1, 131072, messages) == 1


def test_output_budget_accounts_for_input_and_reserve():
    messages = [{"role": "user", "content": "x" * 4000}]  # 1334 tokens at 3 c/t
    assert OUTPUT_CONTEXT_RESERVE == 2048
    assert output_safety_headroom(4096) == 1024  # window // 4 below 8192
    # 4096 - 1334 - 1024 = 1738 remaining; the reserve is 1024 (window // 4).
    assert resolve_max_tokens(None, 4096, messages) == 1024
    # A larger request in the same small window is clamped to what is left:
    # prompt + output + headroom can never exceed the window.
    requested = resolve_max_tokens(4096, 4096, messages)
    assert requested == 4096 - 1334 - 1024
    assert 1334 + requested + output_safety_headroom(4096) <= 4096


def test_output_budget_does_not_guarantee_minimum_when_context_short():
    messages = [{"role": "user", "content": "x" * 8000}]  # ~2000 tokens
    assert MIN_OUTPUT_TOKENS == 1024
    # 2048 - 2000 - 2048 < 0: the minimum is NOT forced past remaining context.
    assert resolve_max_tokens(None, 2048, messages) == 1


def test_output_budget_unknown_context_uses_conservative_fallback():
    messages = [{"role": "user", "content": "hi"}]
    assert resolve_max_tokens(None, None, messages) == DEFAULT_OUTPUT_TOKENS
    assert resolve_max_tokens(999, None, messages) == 999
    # Without a window there is no room arithmetic to trust, so the hard
    # ceiling is still enforced.
    assert resolve_max_tokens(999_999, None, messages) == MAX_OUTPUT_TOKENS


async def test_chat_uses_resolved_model_context_for_output_budget(
    client, test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)
    captured = {}

    async def fake_ensure(_db, _model):
        return _ready_model()  # context_window = 131072

    async def fake_complete(model, messages, **kwargs):
        captured.update(kwargs)
        return "ok", 1, 1

    monkeypatch.setattr(kllm_service, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(llm_service, "complete_managed", fake_complete)

    response = client.post("/api/v1/chat/completions", json=_chat_payload())
    assert response.status_code == 200, response.text
    # 131072 window, no explicit request: the default reply budget is used and
    # stays inside the model ceiling.
    assert captured["max_tokens"] == DEFAULT_OUTPUT_TOKENS


# ---- finish-reason propagation ---------------------------------------------


async def test_chat_stream_preserves_length_finish_reason(
    client, test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)

    async def fake_ensure(_db, _model):
        return _ready_model()

    async def fake_stream(_model, _messages, **_kwargs):
        yield kllm_client.ContentDelta("partial")
        yield StreamMeta("done", {"finish_reason": "length"})
        yield StreamMeta("end", {})

    monkeypatch.setattr(kllm_service, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(kllm_client.kllm_chat_client, "stream", fake_stream)

    with client.stream(
        "POST", "/api/v1/chat/completions", json=_chat_payload(stream=True)
    ) as response:
        body = "".join(response.iter_text())

    events = _parse_sse(body)
    assert [e for e in events if e["type"] == "delta"] == [
        {"type": "delta", "content": "partial"}
    ]
    assert events[-1] == {"type": "done", "finish_reason": "length"}


async def test_chat_stream_end_marker_keeps_default_stop(
    client, test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)

    async def fake_ensure(_db, _model):
        return _ready_model()

    async def fake_stream(_model, _messages, **_kwargs):
        yield kllm_client.ContentDelta("ok")
        yield StreamMeta("end", {})

    monkeypatch.setattr(kllm_service, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(kllm_client.kllm_chat_client, "stream", fake_stream)

    with client.stream(
        "POST", "/api/v1/chat/completions", json=_chat_payload(stream=True)
    ) as response:
        body = "".join(response.iter_text())

    assert _parse_sse(body)[-1] == {"type": "done", "finish_reason": "stop"}


async def test_chat_stream_forwards_the_confirmed_model_event(
    client, test_db, gateway_enabled, monkeypatch
):
    """The model event is the only source the client may treat as confirmed."""
    await _seed_managed_provider(test_db)

    async def fake_ensure(_db, _model):
        return _ready_model()

    async def fake_stream(_model, _messages, **_kwargs):
        yield StreamMeta("model", {"name": "qwen3.8-27b:latest"})
        yield kllm_client.ContentDelta("hi")
        yield StreamMeta("done", {"finish_reason": "stop"})
        yield StreamMeta("end", {})

    monkeypatch.setattr(kllm_service, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(kllm_client.kllm_chat_client, "stream", fake_stream)

    with client.stream(
        "POST", "/api/v1/chat/completions", json=_chat_payload(stream=True)
    ) as response:
        body = "".join(response.iter_text())

    events = _parse_sse(body)
    # The confirmed id is forwarded verbatim, and it is never content.
    assert {"type": "model", "name": "qwen3.8-27b:latest"} in events
    assert [e for e in events if e["type"] == "delta"] == [
        {"type": "delta", "content": "hi"}
    ]
    assert events[-1] == {"type": "done", "finish_reason": "stop"}

async def test_chat_stream_without_a_terminal_event_is_incomplete(
    client, test_db, gateway_enabled, monkeypatch
):
    """A stream that stops without done/end must never look like a clean stop."""
    await _seed_managed_provider(test_db)

    async def fake_ensure(_db, _model):
        return _ready_model()

    async def fake_stream(_model, _messages, **_kwargs):
        yield kllm_client.ContentDelta("partial")
        # No StreamMeta("done"/"end"): the connection simply stopped.

    monkeypatch.setattr(kllm_service, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(kllm_client.kllm_chat_client, "stream", fake_stream)

    with client.stream(
        "POST", "/api/v1/chat/completions", json=_chat_payload(stream=True)
    ) as response:
        body = "".join(response.iter_text())

    events = _parse_sse(body)
    assert [e for e in events if e["type"] == "delta"] == [
        {"type": "delta", "content": "partial"}
    ]
    assert events[-1] == {"type": "done", "finish_reason": INCOMPLETE_FINISH_REASON}


async def test_chat_non_streaming_returns_the_provider_finish_reason(
    client, test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)

    async def fake_ensure(_db, _model):
        return _ready_model()

    async def fake_complete(_model, _messages, **_kwargs):
        return "cut off", 5, 7, "length"

    monkeypatch.setattr(kllm_service, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(llm_service, "complete_managed", fake_complete)

    response = client.post("/api/v1/chat/completions", json=_chat_payload())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["finish_reason"] == "length"
    assert body["content"] == "cut off"
    assert body["usage"] == {"prompt_tokens": 5, "completion_tokens": 7}


async def test_chat_non_streaming_reports_an_unknown_reason_as_null(
    client, test_db, gateway_enabled, monkeypatch
):
    """Legacy three-tuple clients stay supported without inventing a "stop"."""
    await _seed_managed_provider(test_db)

    async def fake_ensure(_db, _model):
        return _ready_model()

    async def fake_complete(_model, _messages, **_kwargs):
        return "ok", 1, 1

    monkeypatch.setattr(kllm_service, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(llm_service, "complete_managed", fake_complete)

    response = client.post("/api/v1/chat/completions", json=_chat_payload())
    assert response.status_code == 200, response.text
    assert response.json()["finish_reason"] is None


async def test_chat_clamps_an_oversized_max_tokens_to_the_window(
    client, test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)
    captured = {}

    async def fake_ensure(_db, _model):
        return dataclasses.replace(_ready_model(), context_window=8192)

    async def fake_complete(_model, _messages, **kwargs):
        captured.update(kwargs)
        return "ok", 1, 1, "stop"

    monkeypatch.setattr(kllm_service, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(llm_service, "complete_managed", fake_complete)

    # 16384 is the largest value the request model accepts, yet it cannot fit an
    # 8192-token window: the endpoint clamps it before fitting the prompt.
    response = client.post(
        "/api/v1/chat/completions", json=_chat_payload(max_tokens=MAX_OUTPUT_TOKENS)
    )
    assert response.status_code == 200, response.text
    expected = max_output_tokens_for_window(8192)
    assert expected == 8192 - output_safety_headroom(8192) - MIN_INPUT_TOKENS
    assert expected < MAX_OUTPUT_TOKENS
    assert captured["max_tokens"] == expected
    assert captured["max_tokens"] == clamp_requested_max_tokens(MAX_OUTPUT_TOKENS, 8192)
    # The request never reserves more output than the window can hold.
    assert 8192 - captured["max_tokens"] - output_safety_headroom(8192) >= MIN_INPUT_TOKENS



async def test_chat_stream_keepalive_is_not_forwarded(
    client, test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)

    async def fake_ensure(_db, _model):
        return _ready_model()

    async def fake_stream(_model, _messages, **_kwargs):
        yield StreamMeta("keepalive", {})
        yield kllm_client.ContentDelta("ok")
        yield StreamMeta("done", {"finish_reason": "stop"})
        yield StreamMeta("end", {})

    monkeypatch.setattr(kllm_service, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(kllm_client.kllm_chat_client, "stream", fake_stream)

    with client.stream(
        "POST", "/api/v1/chat/completions", json=_chat_payload(stream=True)
    ) as response:
        body = "".join(response.iter_text())

    events = _parse_sse(body)
    assert [e for e in events if e["type"] == "delta"] == [
        {"type": "delta", "content": "ok"}
    ]
    assert not any(e["type"] == "status" for e in events)
    assert not any(e["type"] == "keepalive" for e in events)
    assert events[-1] == {"type": "done", "finish_reason": "stop"}


# ---- keepalive / timeout behaviour ------------------------------------------


class _ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


async def _collect_stream_chat_sse() -> list[dict]:
    body = "".join(
        [
            event
            async for event in stream_chat_sse(
                _ConnectedRequest(),
                user_id="keepalive-test",
                model=MODEL,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=64,
                temperature=None,
            )
        ]
    )
    return _parse_sse(body)


async def test_keepalive_resets_idle_deadline(monkeypatch):
    monkeypatch.setattr(chat_service, "IDLE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(chat_service, "FIRST_TOKEN_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(chat_service, "TOTAL_TIMEOUT_SECONDS", 5)

    async def fake_stream(*_args, **_kwargs):
        yield kllm_client.ContentDelta("start")
        await asyncio.sleep(0.03)
        yield StreamMeta("keepalive", {})
        await asyncio.sleep(0.03)
        yield StreamMeta("keepalive", {})
        yield kllm_client.ContentDelta("end")
        yield StreamMeta("end", {})

    monkeypatch.setattr(llm_service, "stream_managed_completion", fake_stream)
    events = await _collect_stream_chat_sse()
    assert [e for e in events if e["type"] == "delta"] == [
        {"type": "delta", "content": "start"},
        {"type": "delta", "content": "end"},
    ]
    assert not any(e["type"] == "error" for e in events)
    assert events[-1] == {"type": "done", "finish_reason": "stop"}


async def test_total_timeout_is_not_reset_by_keepalives(monkeypatch):
    monkeypatch.setattr(chat_service, "IDLE_TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(chat_service, "FIRST_TOKEN_TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(chat_service, "TOTAL_TIMEOUT_SECONDS", 0.1)

    async def fake_stream(*_args, **_kwargs):
        while True:
            await asyncio.sleep(0.02)
            yield StreamMeta("keepalive", {})

    monkeypatch.setattr(llm_service, "stream_managed_completion", fake_stream)
    events = await _collect_stream_chat_sse()
    assert events[-1]["type"] == "error"
    assert events[-1]["code"] == "timeout"


async def test_stalled_stream_is_bounded(monkeypatch):
    monkeypatch.setattr(chat_service, "FIRST_TOKEN_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(chat_service, "TOTAL_TIMEOUT_SECONDS", 5)

    async def never_yields(*_args, **_kwargs):
        await asyncio.sleep(10)
        yield kllm_client.ContentDelta("too late")

    monkeypatch.setattr(llm_service, "stream_managed_completion", never_yields)
    events = await _collect_stream_chat_sse()
    assert events[-1]["type"] == "error"
    assert events[-1]["code"] == "timeout"


# ---- live telemetry forwarding ---------------------------------------------


async def test_chat_stream_forwards_progress_and_model_without_changing_finish_reason(
    client, test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)

    async def fake_ensure(_db, _model):
        return _ready_model()

    async def fake_stream(_model, _messages, **_kwargs):
        yield kllm_client.ContentDelta("partial")
        yield StreamMeta("progress", {"cache": 10, "processed": 40, "total": 80})
        yield StreamMeta("model", {"name": "qwen3.8-27b"})
        yield StreamMeta("timings", {"gen_n": 6, "gen_ms": 250})
        yield StreamMeta("usage", {"prompt_tokens": 20, "completion_tokens": 6})
        yield StreamMeta("done", {"finish_reason": "length"})
        yield StreamMeta("end", {})

    monkeypatch.setattr(kllm_service, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(kllm_client.kllm_chat_client, "stream", fake_stream)

    with client.stream(
        "POST", "/api/v1/chat/completions", json=_chat_payload(stream=True)
    ) as response:
        body = "".join(response.iter_text())

    events = _parse_sse(body)
    assert {"type": "progress", "cache": 10, "processed": 40, "total": 80} in events
    assert {"type": "model", "name": "qwen3.8-27b"} in events
    assert [e for e in events if e["type"] == "delta"] == [
        {"type": "delta", "content": "partial"}
    ]
    assert events[-1] == {"type": "done", "finish_reason": "length"}


async def test_telemetry_events_do_not_terminate_a_longer_stream(monkeypatch):
    async def fake_stream(*_args, **_kwargs):
        for i in range(20):
            yield StreamMeta("progress", {"cache": 0, "processed": i, "total": 20})
            yield kllm_client.ContentDelta(f"t{i},")
        yield StreamMeta("done", {"finish_reason": "stop"})

    monkeypatch.setattr(llm_service, "stream_managed_completion", fake_stream)
    events = await _collect_stream_chat_sse()
    deltas = "".join(e["content"] for e in events if e["type"] == "delta")
    assert deltas == "".join(f"t{i}," for i in range(20))
    assert not any(e["type"] == "error" for e in events)
    assert events[-1] == {"type": "done", "finish_reason": "stop"}
    # No content is held back until the terminal event.
    done_index = next(i for i, e in enumerate(events) if e["type"] == "done")
    assert sum(1 for e in events[:done_index] if e["type"] == "delta") == 20
