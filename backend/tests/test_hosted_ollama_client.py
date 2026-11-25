"""Mocked unit tests for the hosted Ollama transport client.

These use httpx.MockTransport. They are unit/regression tests only and are NOT
proof of live compatibility. No live inference, wake or model load is performed.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.ai import hosted_ollama_client
from app.ai.kllm_client import ContentDelta, StreamMeta
from app.core import config as config_module
from app.services import hosted_ollama_service as hosted

BASE = "http://hosted.test:11434"
SECRET = "sk-THIS-SHOULD-NOT-APPEAR"
MODEL = "qwen3:1.7b-q4_K_M"


@pytest.fixture(autouse=True)
def _configure(monkeypatch):
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_ENABLED", True, raising=False)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_BASE_URL", BASE, raising=False)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_TOKEN", None, raising=False)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_URL_TOKEN", None, raising=False)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_KEEP_ALIVE", "5m", raising=False)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_WAKE_ENABLED", False, raising=False)
    monkeypatch.setattr(config_module.settings, "REDIS_URL", None, raising=False)
    hosted.reset_runtime_state()
    yield
    hosted.reset_runtime_state()


def _install_mock(monkeypatch, handler) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(hosted, "_get_client", lambda: client)
    return client


def _capture(monkeypatch, *, status=200, body=None):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(status, json=body or {})

    _install_mock(monkeypatch, handler)
    return seen


def test_complete_builds_exact_ollama_request(monkeypatch):
    seen = _capture(
        monkeypatch,
        body={
            "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3},
        },
    )
    result = asyncio.run(
        hosted_ollama_client.hosted_ollama_client.complete(
            MODEL,
            [{"role": "user", "content": "hi"}],
            max_tokens=64,
            temperature=0.3,
        )
    )
    request = seen["request"]
    assert request.method == "POST"
    assert str(request.url) == f"{BASE}/v1/chat/completions"
    payload = json.loads(request.content)
    assert payload["model"] == MODEL
    assert payload["max_tokens"] == 64
    assert payload["temperature"] == 0.3
    assert payload["keep_alive"] == "5m"
    assert payload["stream"] is False
    # reasoning_effort is a kLLM concept and must not be forwarded to Ollama.
    assert "reasoning_effort" not in payload
    assert result.content == "hello"
    assert result.prompt_tokens == 7
    assert result.completion_tokens == 3


def test_complete_sends_bearer_token_only_server_side(monkeypatch):
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_TOKEN", SECRET, raising=False)
    seen = _capture(monkeypatch, body={"choices": [{"message": {"content": "ok"}}]})
    asyncio.run(
        hosted_ollama_client.hosted_ollama_client.complete(
            MODEL, [{"role": "user", "content": "hi"}], max_tokens=8
        )
    )
    assert seen["request"].headers["Authorization"] == f"Bearer {SECRET}"


def test_stream_normalizes_deltas_usage_and_done(monkeypatch):
    frames = [
        {"model": MODEL, "choices": [{"delta": {"content": "Hel"}, "finish_reason": None}]},
        {"model": MODEL, "choices": [{"delta": {"content": "lo"}, "finish_reason": None}]},
        {"model": MODEL, "choices": [{"delta": {}, "finish_reason": "stop"}]},
        {"usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}},
    ]
    body = "".join(f"data: {json.dumps(f)}\n\n" for f in frames) + "data: [DONE]\n\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    _install_mock(monkeypatch, handler)

    async def collect():
        return [
            item
            async for item in hosted_ollama_client.hosted_ollama_client.stream(
                MODEL, [{"role": "user", "content": "hi"}], max_tokens=16
            )
        ]

    items = asyncio.run(collect())
    deltas = [str(i) for i in items if isinstance(i, ContentDelta)]
    assert deltas == ["Hel", "lo"]
    assert StreamMeta("usage", {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}) in items
    assert StreamMeta("done", {"finish_reason": "stop"}) in items
    assert StreamMeta("model", {"name": MODEL}) in items
    assert StreamMeta("end", {}) in items


def test_stream_thinking_is_presence_only(monkeypatch):
    frames = [
        {"choices": [{"delta": {"reasoning_content": "secret reasoning"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": "answer"}, "finish_reason": "stop"}]},
    ]
    body = "".join(f"data: {json.dumps(f)}\n\n" for f in frames)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    _install_mock(monkeypatch, handler)

    async def collect():
        return [
            item
            async for item in hosted_ollama_client.hosted_ollama_client.stream(
                MODEL, [{"role": "user", "content": "hi"}], max_tokens=16
            )
        ]

    items = asyncio.run(collect())
    assert StreamMeta("status", {"status": "thinking"}) in items
    # Raw reasoning text is never forwarded as content.
    assert all("secret reasoning" not in str(i) for i in items if isinstance(i, ContentDelta))


def test_status_error_mapping_is_safe(monkeypatch):
    _capture(monkeypatch, status=404, body={"error": "model not found"})
    with pytest.raises(hosted_ollama_client.HostedClientError) as exc:
        asyncio.run(
            hosted_ollama_client.hosted_ollama_client.complete(
                MODEL, [{"role": "user", "content": "hi"}], max_tokens=8
            )
        )
    assert exc.value.reason_code == "model_not_found"
    assert SECRET not in exc.value.message


def test_auth_error_does_not_leak_secret(monkeypatch):
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_TOKEN", SECRET, raising=False)
    _capture(monkeypatch, status=401, body={"error": f"unauthorized {SECRET} {BASE}"})
    with pytest.raises(hosted_ollama_client.HostedClientError) as exc:
        asyncio.run(
            hosted_ollama_client.hosted_ollama_client.complete(
                MODEL, [{"role": "user", "content": "hi"}], max_tokens=8
            )
        )
    assert exc.value.reason_code == "hosted_auth_error"
    assert SECRET not in exc.value.message
    assert BASE not in exc.value.message


PROMPT_TEXT = "the user's private question about margarine"

#: The pre-fix generic sentence. No HTTP 400 path may ever return it again.
LEGACY_REJECTION_MESSAGE = (
    "Hosted Ollama rejected the request as invalid. "
    "Try shortening the conversation and sending it again."
)


def _reject_text(monkeypatch, text, *, status=400):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=text, headers={"content-type": "application/json"})

    _install_mock(monkeypatch, handler)


def _collect_stream():
    async def collect():
        return [
            item
            async for item in hosted_ollama_client.hosted_ollama_client.stream(
                MODEL, [{"role": "user", "content": "hi"}], max_tokens=8
            )
        ]

    return asyncio.run(collect())


def _complete_one():
    return asyncio.run(
        hosted_ollama_client.hosted_ollama_client.complete(
            MODEL, [{"role": "user", "content": "hi"}], max_tokens=8
        )
    )


def _reject_once(monkeypatch, *, body, status=400):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(status, json=body)

    _install_mock(monkeypatch, handler)
    return seen


def test_invalid_request_body_is_classified_and_redacted(monkeypatch, caplog):
    """A hosted 400 is classified without leaking the upstream body."""
    _reject_once(
        monkeypatch,
        body={"error": {"message": f"prompt too long: {PROMPT_TEXT}", "type": "invalid_request_error"}},
    )
    with caplog.at_level("WARNING", logger="app.ai.hosted_ollama_client"):
        with pytest.raises(hosted_ollama_client.HostedClientError) as exc:
            asyncio.run(
                hosted_ollama_client.hosted_ollama_client.complete(
                    MODEL, [{"role": "user", "content": PROMPT_TEXT}], max_tokens=8
                )
            )
    error = exc.value
    assert error.reason_code == "prompt_too_long"
    assert error.structured is True
    assert error.status_code == 400
    # The safe client message is actionable and never echoes the prompt.
    assert "longer" in error.message.lower()
    assert PROMPT_TEXT not in error.message
    assert BASE not in error.message
    logs = caplog.text
    assert PROMPT_TEXT not in logs
    assert BASE not in logs
    # Only structural diagnostics are logged.
    assert "reason=prompt_too_long" in logs
    assert "matched_hint=" in logs


def test_message_shape_rejection_is_classified(monkeypatch):
    _reject_once(monkeypatch, body={"error": "invalid message role"})
    with pytest.raises(hosted_ollama_client.HostedClientError) as exc:
        asyncio.run(
            hosted_ollama_client.hosted_ollama_client.complete(
                MODEL, [{"role": "user", "content": "hi"}], max_tokens=8
            )
        )
    assert exc.value.reason_code == "invalid_message_shape"
    assert exc.value.structured is True


def test_option_rejection_is_classified(monkeypatch):
    _reject_once(monkeypatch, body={"error": {"message": "invalid duration for keep_alive"}})
    with pytest.raises(hosted_ollama_client.HostedClientError) as exc:
        asyncio.run(
            hosted_ollama_client.hosted_ollama_client.complete(
                MODEL, [{"role": "user", "content": "hi"}], max_tokens=8
            )
        )
    assert exc.value.reason_code == "invalid_option"


def test_unknown_or_non_json_rejection_falls_back_safely(monkeypatch, caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text=f"<html>{PROMPT_TEXT}</html>")

    _install_mock(monkeypatch, handler)
    with caplog.at_level("WARNING", logger="app.ai.hosted_ollama_client"):
        with pytest.raises(hosted_ollama_client.HostedClientError) as exc:
            asyncio.run(
                hosted_ollama_client.hosted_ollama_client.complete(
                    MODEL, [{"role": "user", "content": PROMPT_TEXT}], max_tokens=8
                )
            )
    assert exc.value.reason_code == "upstream_rejected_unclassified"
    assert exc.value.structured is True
    assert PROMPT_TEXT not in exc.value.message
    assert PROMPT_TEXT not in caplog.text
    assert "reason=upstream_rejected_unclassified" in caplog.text


def test_stream_invalid_request_is_classified(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "input length exceeds context window"}})

    _install_mock(monkeypatch, handler)

    async def collect():
        return [
            item
            async for item in hosted_ollama_client.hosted_ollama_client.stream(
                MODEL, [{"role": "user", "content": "hi"}], max_tokens=8
            )
        ]

    with pytest.raises(hosted_ollama_client.HostedClientError) as exc:
        asyncio.run(collect())
    assert exc.value.reason_code == "prompt_too_long"
    assert exc.value.structured is True


def test_non_400_statuses_stay_unstructured(monkeypatch):
    _reject_once(monkeypatch, status=404, body={"error": "model not found"})
    with pytest.raises(hosted_ollama_client.HostedClientError) as exc:
        asyncio.run(
            hosted_ollama_client.hosted_ollama_client.complete(
                MODEL, [{"role": "user", "content": "hi"}], max_tokens=8
            )
        )
    assert exc.value.reason_code == "model_not_found"
    assert exc.value.structured is False


def test_permit_released_after_completion(monkeypatch):
    _capture(monkeypatch, body={"choices": [{"message": {"content": "ok"}}]})
    asyncio.run(
        hosted_ollama_client.hosted_ollama_client.complete(
            MODEL, [{"role": "user", "content": "hi"}], max_tokens=8
        )
    )
    status = hosted.concurrency_status()
    assert status["inflight"] == 0
    assert status["queued"] == 0


def test_permit_released_after_stream(monkeypatch):
    body = 'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    _install_mock(monkeypatch, handler)

    async def collect():
        return [
            item
            async for item in hosted_ollama_client.hosted_ollama_client.stream(
                MODEL, [{"role": "user", "content": "hi"}], max_tokens=8
            )
        ]

    asyncio.run(collect())
    status = hosted.concurrency_status()
    assert status["inflight"] == 0
    assert status["queued"] == 0


# --- gateway login handshake ------------------------------------------------


def _gateway_handler(seen, *, final):
    """Simulate a private-port gateway: tokenized POST answers with 303 + cookie."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/v1/chat/completions":
            return httpx.Response(
                303,
                headers={"location": "/gw/login", "set-cookie": "gw=ok; Path=/"},
            )
        return final

    return handler


def test_complete_completes_gateway_login_handshake(monkeypatch):
    monkeypatch.setattr(
        config_module.settings, "REVORA_HOSTED_OLLAMA_URL_TOKEN", "gw-token", raising=False
    )
    seen: list[httpx.Request] = []
    final = httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    _install_mock(monkeypatch, _gateway_handler(seen, final=final))

    result = _complete_one()

    assert result.content == "ok"
    assert [r.url.path for r in seen] == ["/v1/chat/completions", "/gw/login"]
    # First hop carries the gateway token; the retry relies on the cookie.
    assert "_token=gw-token" in str(seen[0].url)
    assert "_token" not in str(seen[1].url)
    assert seen[1].headers.get("cookie") == "gw=ok"


def test_stream_completes_gateway_login_handshake(monkeypatch):
    monkeypatch.setattr(
        config_module.settings, "REVORA_HOSTED_OLLAMA_URL_TOKEN", "gw-token", raising=False
    )
    seen: list[httpx.Request] = []
    body = 'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
    final = httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
    _install_mock(monkeypatch, _gateway_handler(seen, final=final))

    items = _collect_stream()

    assert [str(i) for i in items if isinstance(i, ContentDelta)] == ["ok"]
    assert [r.url.path for r in seen] == ["/v1/chat/completions", "/gw/login"]
    assert "_token" not in str(seen[1].url)
    assert seen[1].headers.get("cookie") == "gw=ok"


def test_cross_origin_gateway_redirect_is_never_followed(monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(303, headers={"location": "http://evil.test/steal"})

    _install_mock(monkeypatch, handler)

    with pytest.raises(hosted_ollama_client.HostedClientError) as exc:
        _complete_one()
    # Only the first hop was attempted and the reason is explicit.
    assert len(seen) == 1
    assert "disallowed redirect" in exc.value.message.lower()
    assert "evil.test" not in exc.value.message


def test_cross_origin_gateway_redirect_rejected_on_stream(monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(303, headers={"location": "http://evil.test/steal"})

    _install_mock(monkeypatch, handler)

    with pytest.raises(hosted.HostedError) as exc:
        _collect_stream()
    assert len(seen) == 1
    assert getattr(exc.value, "reason_code", None) == "hosted_redirect"
    assert "evil.test" not in exc.value.message


# --- keep_alive validation --------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["5m", "30s", "1h", "-1", "0", "300", "-300", "1.5h", "500ms", "1h30m", ""],
)
def test_keep_alive_accepts_ollama_formats(value):
    assert config_module.keep_alive_is_valid(value) is True
    assert config_module.validate_keep_alive_duration(value) == value


@pytest.mark.parametrize(
    "value", ["5 m", "5minutes", "abc", "1d", "m5", "--1", "5m5", "3600 s", "NaN"]
)
def test_keep_alive_rejects_invalid_formats(value):
    assert config_module.keep_alive_is_valid(value) is False
    with pytest.raises(ValueError):
        config_module.validate_keep_alive_duration(value)


def test_keep_alive_validator_error_does_not_echo_the_value():
    with pytest.raises(ValueError) as exc:
        config_module.validate_keep_alive_duration("super-secret-keep-alive")
    assert "super-secret-keep-alive" not in str(exc.value)
    assert "REVORA_HOSTED_OLLAMA_KEEP_ALIVE" in str(exc.value)


def test_keep_alive_payload_value_sends_unitless_as_number():
    assert config_module.keep_alive_payload_value("5m") == "5m"
    assert config_module.keep_alive_payload_value("-1") == -1
    assert config_module.keep_alive_payload_value(" 300 ") == 300
    assert config_module.keep_alive_payload_value("") == ""


def test_complete_sends_unitless_keep_alive_as_number(monkeypatch):
    monkeypatch.setattr(
        config_module.settings, "REVORA_HOSTED_OLLAMA_KEEP_ALIVE", "-1", raising=False
    )
    seen = _capture(monkeypatch, body={"choices": [{"message": {"content": "ok"}}]})
    _complete_one()
    payload = json.loads(seen["request"].content)
    assert payload["keep_alive"] == -1


# --- Go-duration and unclassified rejections --------------------------------


@pytest.mark.parametrize(
    "upstream",
    [
        '{"error":"time: missing unit in duration \\"300\\""}',
        '{"error":"time: invalid duration \\"5 minutes\\""}',
        '{"error":"time: unknown unit \\"d\\" in duration \\"1d\\""}',
        '{"error":{"message":"invalid duration for keep_alive","type":"invalid_request_error"}}',
    ],
)
def test_go_duration_rejections_are_classified(monkeypatch, upstream):
    _reject_text(monkeypatch, upstream)
    with pytest.raises(hosted_ollama_client.HostedClientError) as exc:
        _complete_one()
    assert exc.value.reason_code == "invalid_option"
    assert "keep_alive" in exc.value.message
    assert exc.value.message != LEGACY_REJECTION_MESSAGE


def test_empty_body_is_unclassified_and_never_blames_context(monkeypatch, caplog):
    _reject_text(monkeypatch, "")
    with caplog.at_level("WARNING", logger="app.ai.hosted_ollama_client"):
        with pytest.raises(hosted_ollama_client.HostedClientError) as exc:
            _complete_one()
    assert exc.value.reason_code == "upstream_rejected_unclassified"
    assert exc.value.structured is True
    message = exc.value.message.lower()
    assert "shortening" not in message
    assert "too long" not in message
    assert "context" not in message
    logs = caplog.text
    assert "reason=upstream_rejected_unclassified" in logs
    assert "path=complete" in logs
    assert "upstream_bytes=0" in logs
    assert "matched_hint=none" in logs
    assert "final_role=user" in logs
    assert "context_window=unknown" in logs
    assert "output_budget=" in logs
    assert "keep_alive_ok=True" in logs


def test_unclassified_surfaces_allowlisted_upstream_type(monkeypatch):
    _reject_once(
        monkeypatch,
        body={"error": {"message": "invalid request", "type": "invalid_request_error"}},
    )
    with pytest.raises(hosted_ollama_client.HostedClientError) as exc:
        _complete_one()
    assert exc.value.reason_code == "upstream_rejected_unclassified"
    assert "invalid_request_error" in exc.value.message


def test_html_proxy_body_never_leaks(monkeypatch, caplog):
    _reject_text(monkeypatch, "<html><body>gateway denies this hop: tok-abc-123</body></html>")
    with caplog.at_level("WARNING", logger="app.ai.hosted_ollama_client"):
        with pytest.raises(hosted_ollama_client.HostedClientError) as exc:
            _complete_one()
    assert exc.value.reason_code == "upstream_rejected_unclassified"
    assert "tok-abc-123" not in exc.value.message
    assert "tok-abc-123" not in caplog.text
    assert "<html>" not in exc.value.message


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"error": "invalid request"},
        {"error": {"message": "invalid request", "type": "invalid_request_error"}},
        {"error": "bad"},
        {"unexpected": [1, 2, 3]},
    ],
)
def test_no_400_path_returns_the_legacy_message(monkeypatch, body):
    _reject_once(monkeypatch, body=body)
    with pytest.raises(hosted_ollama_client.HostedClientError) as exc:
        _complete_one()
    assert exc.value.message != LEGACY_REJECTION_MESSAGE
    assert "Try shortening the conversation" not in exc.value.message


def test_status_error_has_no_duplicate_400_branch():
    """HTTP 400 has exactly one authoritative classification path."""
    error = hosted_ollama_client._status_error(400, MODEL)
    assert "Try shortening the conversation" not in error.message


def test_stream_unclassified_rejection_is_structured(monkeypatch):
    _reject_text(monkeypatch, "")
    with pytest.raises(hosted_ollama_client.HostedClientError) as exc:
        _collect_stream()
    assert exc.value.reason_code == "upstream_rejected_unclassified"
    assert exc.value.structured is True
    assert exc.value.status_code == 400
