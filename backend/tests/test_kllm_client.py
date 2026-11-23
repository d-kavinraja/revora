"""Mocked unit tests for the direct kLLM relay client.

These tests use httpx.MockTransport. They are unit/regression tests only and
are NOT proof of live backend compatibility. No live inference is performed.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.ai import kllm_client
from app.ai.kllm_client import (
    ContentDelta,
    KllmClientError,
    StreamMeta,
)
from app.core import config as config_module

BASE = "http://kllm.test:8080"
SECRET = "sk-THIS-SHOULD-NOT-APPEAR"
MODEL = "qwen3.8-27b"


@pytest.fixture(autouse=True)
def _configure(monkeypatch):
    monkeypatch.setattr(config_module.settings, "KLLM_SERVER_URL", BASE, raising=False)
    monkeypatch.setattr(config_module.settings, "KLLM_GATEWAY_API_KEY", None, raising=False)
    # Isolate the module-level singleton so tests never share a real client.
    original = kllm_client._client
    kllm_client._client = None
    yield
    if kllm_client._client is not None and not kllm_client._client.is_closed:
        # best effort; tests use MockTransport so no real socket is involved
        pass
    kllm_client._client = original


def _install_mock(monkeypatch, handler) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(kllm_client, "_get_client", lambda: client)
    return client


def _capture(monkeypatch, *, status=200, body=None, headers=None):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(status, json=body or {}, headers=headers or {})

    _install_mock(monkeypatch, handler)
    return seen


def test_complete_builds_exact_relay_request(monkeypatch):
    seen = _capture(
        monkeypatch,
        body={
            "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3},
        },
    )
    result = asyncio.run(
        kllm_client.kllm_chat_client.complete(
            MODEL,
            [{"role": "user", "content": "hi"}],
            max_tokens=64,
            temperature=0.3,
            reasoning_effort="medium",
            timeout=12,
        )
    )

    request = seen["request"]
    assert request.method == "POST"
    assert str(request.url) == f"{BASE}/v1/chat/completions"
    payload = json.loads(request.content)
    assert payload["model"] == MODEL
    assert payload["messages"] == [{"role": "user", "content": "hi"}]
    assert payload["stream"] is False
    assert payload["max_tokens"] == 64
    assert payload["temperature"] == 0.3
    assert payload["reasoning_effort"] == "medium"
    assert result.content == "hello"
    assert result.prompt_tokens == 7
    assert result.completion_tokens == 3
    assert result.finish_reason == "stop"


def test_complete_sends_server_key_only_when_real(monkeypatch):
    seen = _capture(monkeypatch, body={"choices": [{"message": {"content": "ok"}}]})
    monkeypatch.setattr(config_module.settings, "KLLM_GATEWAY_API_KEY", SECRET, raising=False)
    asyncio.run(
        kllm_client.kllm_chat_client.complete(
            MODEL, [{"role": "user", "content": "hi"}], max_tokens=8
        )
    )
    assert seen["request"].headers["authorization"] == f"Bearer {SECRET}"

    # Placeholder keys are treated as "no key", matching kLLM's own auth.
    monkeypatch.setattr(
        config_module.settings, "KLLM_GATEWAY_API_KEY", "sk-kllm-local", raising=False
    )
    asyncio.run(
        kllm_client.kllm_chat_client.complete(
            MODEL, [{"role": "user", "content": "hi"}], max_tokens=8
        )
    )
    assert "authorization" not in seen["request"].headers


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (401, "kllm_auth_error"),
        (403, "kllm_auth_error"),
        (404, "model_not_found"),
        (400, "invalid_request"),
        (429, "kllm_busy"),
        (503, "kllm_busy"),
        (500, "kllm_unavailable"),
        (502, "kllm_unavailable"),
    ],
)
def test_complete_maps_http_errors_to_safe_reasons(monkeypatch, status, reason):
    seen = _capture(monkeypatch, status=status, body={"error": {"message": SECRET}})
    with pytest.raises(KllmClientError) as exc:
        asyncio.run(
            kllm_client.kllm_chat_client.complete(
                MODEL, [{"role": "user", "content": "hi"}], max_tokens=8
            )
        )
    assert exc.value.reason_code == reason
    assert SECRET not in str(exc.value)
    assert BASE not in str(exc.value)
    assert "authorization" not in str(exc.value).lower()
    assert seen["request"] is not None


def test_stream_yields_text_and_presence_gated_metadata(monkeypatch):
    body = (
        ": kllm: prefilling\n\n"
        'data: {"choices":[{"delta":{"content":"Hel"},"index":0}]}\n\n'
        'data: {"choices":[{"delta":{"reasoning_content":"HIDDEN-CHAIN"},"index":0}]}\n\n'
        'data: {"choices":[{"delta":{"content":"lo"},"index":0}]}\n\n'
        'data: {"usage":{"prompt_tokens":10,"completion_tokens":2,'
        '"cache_read_input_tokens":4},'
        '"timings":{"predicted_per_second":45.5,"prompt_per_second":1200.0,'
        '"cache_n":4,"predicted_n":2},'
        '"choices":[{"delta":{},"finish_reason":"stop","index":0}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request):
        payload = json.loads(request.content)
        assert payload["stream"] is True
        assert payload["reasoning_effort"] == "high"
        assert payload["stream_options"] == {"include_usage": True}
        return httpx.Response(
            200, text=body, headers={"content-type": "text/event-stream"}
        )

    _install_mock(monkeypatch, handler)

    async def consume():
        return [
            item
            async for item in kllm_client.kllm_chat_client.stream(
                MODEL,
                [{"role": "user", "content": "hi"}],
                max_tokens=32,
                reasoning_effort="high",
            )
        ]

    items = asyncio.run(consume())
    assert [str(i) for i in items if isinstance(i, ContentDelta)] == ["Hel", "lo"]
    assert any(
        isinstance(i, StreamMeta) and i.kind == "status" for i in items
    )
    usage = next(i.data for i in items if isinstance(i, StreamMeta) and i.kind == "usage")
    assert usage == {
        "prompt_tokens": 10,
        "completion_tokens": 2,
        "cache_read_input_tokens": 4,
    }
    timings = next(
        i.data for i in items if isinstance(i, StreamMeta) and i.kind == "timings"
    )
    assert timings == {
        "prompt_tps": 1200.0,
        "gen_tps": 45.5,
        "cache_n": 4,
        "gen_n": 2,
    }
    assert any(
        isinstance(i, StreamMeta)
        and i.kind == "done"
        and i.data.get("finish_reason") == "stop"
        for i in items
    )
    # Presence only: raw hidden reasoning text is never forwarded.
    assert all("HIDDEN-CHAIN" not in str(i) for i in items)


def test_stream_ignores_malformed_events_and_missing_metadata(monkeypatch):
    body = (
        "data: {not json}\n\n"
        'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
        "data: [DONE]\n\n"
    )
    _install_mock(
        monkeypatch,
        lambda request: httpx.Response(
            200, text=body, headers={"content-type": "text/event-stream"}
        ),
    )

    async def consume():
        return [
            item
            async for item in kllm_client.kllm_chat_client.stream(
                MODEL, [{"role": "user", "content": "hi"}], max_tokens=8
            )
        ]

    items = asyncio.run(consume())
    assert [str(i) for i in items if isinstance(i, ContentDelta)] == ["ok"]
    assert not any(isinstance(i, StreamMeta) and i.kind in {"usage", "timings"} for i in items)


def test_stream_error_event_becomes_safe_error(monkeypatch):
    body = f'data: {{"error":{{"message":"secret {SECRET}"}}}}\n\n'
    _install_mock(
        monkeypatch,
        lambda request: httpx.Response(
            200, text=body, headers={"content-type": "text/event-stream"}
        ),
    )

    async def consume():
        return [
            item
            async for item in kllm_client.kllm_chat_client.stream(
                MODEL, [{"role": "user", "content": "hi"}], max_tokens=8
            )
        ]

    with pytest.raises(KllmClientError) as exc:
        asyncio.run(consume())
    assert exc.value.reason_code == "kllm_error"
    assert SECRET not in str(exc.value)


def test_stream_cancellation_closes_response(monkeypatch):
    released = {"closed": False}

    def handler(request):
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"x"}}]}\n\n',
            headers={"content-type": "text/event-stream"},
        )

    client = _install_mock(monkeypatch, handler)

    async def consume_one_then_close():
        gen = kllm_client.kllm_chat_client.stream(
            MODEL, [{"role": "user", "content": "hi"}], max_tokens=8
        )
        first = await gen.__anext__()
        assert str(first) == "x"
        await gen.aclose()
        released["closed"] = True

    asyncio.run(consume_one_then_close())
    assert released["closed"] is True
    assert not client.is_closed  # shared client survives; only the stream closed


def test_singleton_lifecycle(monkeypatch):
    first = kllm_client._get_client()
    second = kllm_client._get_client()
    assert first is second
    asyncio.run(kllm_client.aclose())
    assert first.is_closed
    third = kllm_client._get_client()
    assert third is not first
    asyncio.run(kllm_client.aclose())


def test_client_timeout_configuration_is_bounded():
    """The shared client must use a bounded read timeout, not read=None."""
    timeout = kllm_client._get_client().timeout
    assert timeout.connect == 10.0
    assert timeout.read is not None
    assert timeout.read == kllm_client.HTTP_READ_TIMEOUT_SECONDS
    assert timeout.write == 120.0
    assert timeout.pool == 10.0


def test_http_read_timeout_respects_chat_service_hierarchy():
    """The HTTP backstop must not preempt the authoritative Chat timeouts."""
    from app.services import chat_service

    read = kllm_client._get_client().timeout.read
    assert read is not None

    # Service-level timeouts are unchanged and remain the primary authority.
    assert chat_service.FIRST_TOKEN_TIMEOUT_SECONDS == 90
    assert chat_service.IDLE_TIMEOUT_SECONDS == 60
    assert chat_service.TOTAL_TIMEOUT_SECONDS == 600

    # The HTTP read timeout only bounds a stalled pooled connection: longer than
    # first-token/idle so it cannot preempt them, shorter than total so it stays
    # a backstop rather than the primary timeout.
    assert read > chat_service.FIRST_TOKEN_TIMEOUT_SECONDS
    assert read > chat_service.IDLE_TIMEOUT_SECONDS
    assert read < chat_service.TOTAL_TIMEOUT_SECONDS


def test_complete_read_timeout_maps_to_safe_error(monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("upstream stalled secret", request=request)

    _install_mock(monkeypatch, handler)
    with pytest.raises(KllmClientError) as exc:
        asyncio.run(
            kllm_client.kllm_chat_client.complete(
                MODEL, [{"role": "user", "content": "hi"}], max_tokens=8
            )
        )
    assert exc.value.reason_code == "timeout"
    assert "upstream stalled secret" not in str(exc.value)
    assert BASE not in str(exc.value)


def test_stream_read_timeout_maps_to_safe_error(monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("upstream stalled secret", request=request)

    _install_mock(monkeypatch, handler)

    async def consume():
        return [
            item
            async for item in kllm_client.kllm_chat_client.stream(
                MODEL, [{"role": "user", "content": "hi"}], max_tokens=8
            )
        ]

    with pytest.raises(KllmClientError) as exc:
        asyncio.run(consume())
    assert exc.value.reason_code == "timeout"
    assert "upstream stalled secret" not in str(exc.value)
    assert BASE not in str(exc.value)


def _consume_mock_stream(monkeypatch, body: str):
    _install_mock(
        monkeypatch,
        lambda request: httpx.Response(
            200, text=body, headers={"content-type": "text/event-stream"}
        ),
    )

    async def consume():
        return [
            item
            async for item in kllm_client.kllm_chat_client.stream(
                MODEL, [{"role": "user", "content": "hi"}], max_tokens=8
            )
        ]

    return asyncio.run(consume())


def test_done_marker_does_not_overwrite_upstream_finish_reason(monkeypatch):
    items = _consume_mock_stream(
        monkeypatch,
        'data: {"choices":[{"delta":{"content":"partial"},"index":0}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"length","index":0}]}\n\n'
        "data: [DONE]\n\n",
    )
    done = [i for i in items if isinstance(i, StreamMeta) and i.kind == "done"]
    assert len(done) == 1
    assert done[0].data == {"finish_reason": "length"}
    assert any(isinstance(i, StreamMeta) and i.kind == "end" for i in items)
    assert [str(i) for i in items if isinstance(i, ContentDelta)] == ["partial"]


def test_done_marker_without_reason_is_not_a_finish_reason(monkeypatch):
    items = _consume_mock_stream(
        monkeypatch,
        'data: {"choices":[{"delta":{"content":"ok"},"index":0}]}\n\n'
        "data: [DONE]\n\n",
    )
    assert not any(isinstance(i, StreamMeta) and i.kind == "done" for i in items)
    assert any(isinstance(i, StreamMeta) and i.kind == "end" for i in items)


def test_keepalive_is_internal_only(monkeypatch):
    items = _consume_mock_stream(
        monkeypatch,
        ": kllm: prefilling\n\n"
        'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n',
    )
    assert any(isinstance(i, StreamMeta) and i.kind == "keepalive" for i in items)
    assert [str(i) for i in items if isinstance(i, ContentDelta)] == ["ok"]
    assert not any(isinstance(i, StreamMeta) and i.kind == "done" for i in items)


def test_stream_request_enables_real_per_token_timings(monkeypatch):
    seen = {}

    def handler(request):
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"x"}}]}\n\n',
            headers={"content-type": "text/event-stream"},
        )

    _install_mock(monkeypatch, handler)
    asyncio.run(_drain_stream())
    assert seen["payload"]["timings_per_token"] is True
    assert seen["payload"]["stream"] is True
    assert seen["payload"]["stream_options"] == {"include_usage": True}


async def _drain_stream():
    return [
        item
        async for item in kllm_client.kllm_chat_client.stream(
            MODEL, [{"role": "user", "content": "hi"}], max_tokens=8
        )
    ]


def test_non_streaming_request_does_not_enable_timings(monkeypatch):
    seen = _capture(monkeypatch, body={"choices": [{"message": {"content": "ok"}}]})
    asyncio.run(
        kllm_client.kllm_chat_client.complete(
            MODEL, [{"role": "user", "content": "hi"}], max_tokens=8
        )
    )
    payload = json.loads(seen["request"].content)
    assert "timings_per_token" not in payload


def test_stream_parses_progress_and_model_telemetry(monkeypatch):
    body = (
        'data: {"model":"qwen3.8-27b","prompt_progress":{"cache":10,"processed":40,"total":80,"time_ms":120},"choices":[{"delta":{},"index":0}]}\n\n'
        'data: {"model":"qwen3.8-27b","timings":{"prompt_n":30,"cache_n":10,"predicted_n":0,"predicted_ms":0},"choices":[{"delta":{},"index":0}]}\n\n'
        'data: {"model":"qwen3.8-27b","timings":{"prompt_n":30,"cache_n":10,"predicted_n":12,"predicted_ms":400},"choices":[{"delta":{"content":"Hi"},"index":0}]}\n\n'
        'data: [DONE]\n\n'
    )
    items = _consume_mock_stream(monkeypatch, body)
    progress = [i for i in items if isinstance(i, StreamMeta) and i.kind == "progress"]
    assert len(progress) == 1
    assert progress[0].data == {"cache": 10, "processed": 40, "total": 80}
    models = [i for i in items if isinstance(i, StreamMeta) and i.kind == "model"]
    assert len(models) == 3
    assert all(m.data == {"name": "qwen3.8-27b"} for m in models)
    timings = [i for i in items if isinstance(i, StreamMeta) and i.kind == "timings"]
    assert len(timings) == 2
    assert timings[1].data["gen_n"] == 12
    assert timings[1].data["gen_ms"] == 400
    assert [str(i) for i in items if isinstance(i, ContentDelta)] == ["Hi"]
    assert not any(isinstance(i, StreamMeta) and i.kind == "done" for i in items)


def test_malformed_telemetry_is_ignored_without_breaking_content(monkeypatch):
    body = (
        'data: {"model":42,"prompt_progress":{"cache":"x","processed":null,"total":"80"},"choices":[{"delta":{}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
    )
    items = _consume_mock_stream(monkeypatch, body)
    assert [str(i) for i in items if isinstance(i, ContentDelta)] == ["ok"]
    assert not any(isinstance(i, StreamMeta) and i.kind in {"progress", "model"} for i in items)


def test_long_multi_chunk_stream_preserves_all_content(monkeypatch):
    chunks = "".join(
        f'data: {{"choices":[{{"delta":{{"content":"part{i},"}}}}]}}\n\n'
        for i in range(120)
    )
    items = _consume_mock_stream(monkeypatch, chunks + "data: [DONE]\n\n")
    text = "".join(str(i) for i in items if isinstance(i, ContentDelta))
    assert text == "".join(f"part{i}," for i in range(120))
    assert sum(1 for i in items if isinstance(i, StreamMeta) and i.kind == "end") == 1
