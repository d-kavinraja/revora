"""Direct HTTP client for the kLLM OpenAI-compatible relay.

This is the transport for the dedicated Revora kLLM Chat pathway. kLLM already
speaks the OpenAI chat-completions protocol, so going through LiteLLM only
added provider assumptions (it rejects kLLM-supported parameters such as
``reasoning_effort`` before any HTTP request is made) and dropped stream
metadata. Here the relay contract is used directly:

* ``POST {KLLM_SERVER_URL}/v1/chat/completions``
* canonical model id, messages, ``stream`` and ``reasoning_effort`` forwarded
  unchanged;
* server-side gateway key only, never exposed to clients;
* stream ``usage`` / ``timings`` / neutral status events are preserved when the
  upstream actually emits them.

All configuration comes from the validated backend settings; no gateway
address or credential is hardcoded into application logic.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.services.kllm_service import KllmError

from .kllm_sse import SseDecoder, SseFrame

logger = logging.getLogger(__name__)

# Mirrors kLLM's placeholder keys (gateway/auth.py:PLACEHOLDER_KEYS): sending one
# of these is equivalent to sending no key at all.
_PLACEHOLDER_KEYS = {"", "sk-change-me", "sk-kllm-local", "changeme"}

# Defensive HTTP-level read timeout. The chat service remains authoritative with
# its first-token (90s), idle (60s) and total (600s) timeouts, all of which are
# shorter than this value except the total; this backstop only fires when a
# single upstream read stalls long enough to pin a pooled connection, so it
# cannot preempt normal Chat timeouts but still bounds resource exhaustion.
HTTP_READ_TIMEOUT_SECONDS = 300.0

# Bounded, long-lived connection pool shared by the kLLM Chat pathway.
_client: httpx.AsyncClient | None = None


class ContentDelta(str):
    """A text delta from kLLM.

    It is a ``str`` subclass so existing string consumers keep working while
    the chat service can still distinguish structured metadata events.
    """


@dataclass(frozen=True)
class StreamMeta:
    """A non-content streaming event produced by the kLLM relay."""

    kind: str  # "usage" | "timings" | "status" | "done" | "end" | "keepalive" | "progress" | "model"
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompletionResult:
    """Normalized result of a non-streaming kLLM completion."""

    content: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    timings: dict[str, Any] = field(default_factory=dict)


class KllmClientError(KllmError):
    """Safe, client-facing error raised by the direct kLLM transport.

    The message never contains raw upstream payloads, URLs, headers or
    exception details; only a stable ``reason_code`` is surfaced to callers.
    """


def _gateway_base_url() -> str:
    """Validate and return the configured relay base URL."""
    raw = str(getattr(settings, "KLLM_SERVER_URL", "") or "").strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise KllmClientError(
            "kLLM is not configured with a valid server URL.",
            reason_code="kllm_not_configured",
        )
    return raw


def _get_client() -> httpx.AsyncClient:
    """Return the shared, lazily created HTTP client (managed lifecycle)."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,
                read=HTTP_READ_TIMEOUT_SECONDS,
                write=120.0,
                pool=10.0,
            ),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            follow_redirects=False,
        )
    return _client


async def aclose() -> None:
    """Close the shared client. Called from the application lifespan shutdown."""
    global _client
    client, _client = _client, None
    if client is not None and not client.is_closed:
        await client.aclose()


def _request_headers(*, stream: bool) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if stream else "application/json",
    }
    key = str(getattr(settings, "KLLM_GATEWAY_API_KEY", "") or "").strip()
    if key not in _PLACEHOLDER_KEYS:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _build_payload(
    model: str,
    messages: Sequence[dict[str, Any]],
    *,
    stream: bool,
    max_tokens: int,
    temperature: float | None,
    reasoning_effort: str | None,
) -> dict[str, Any]:
    """Build the exact kLLM relay request body (no provider translation)."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": list(messages),
        "stream": stream,
        "max_tokens": max_tokens,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    if stream:
        # The relay forwards both flags unchanged to llama-server. The native
        # kLLM UI sends `timings_per_token: true` to receive per-token timings
        # (predicted_n / predicted_ms, prompt_n, cache_n) and `prompt_progress`
        # during prefill — the only authoritative source for live metrics.
        payload["stream_options"] = {"include_usage": True}
        payload["timings_per_token"] = True
    return payload


def _status_error(status: int, model: str) -> KllmClientError:
    """Map an HTTP status to a safe, meaningful error category."""
    if status in (401, 403):
        return KllmClientError(
            "kLLM rejected the server credentials.",
            reason_code="kllm_auth_error",
        )
    if status == 404:
        return KllmClientError(
            f"Model '{model}' was not found in kLLM.",
            reason_code="model_not_found",
        )
    if status == 400:
        return KllmClientError(
            "kLLM rejected the request as invalid. "
            "Try shortening the conversation and sending it again.",
            reason_code="invalid_request",
        )
    if status == 429:
        return KllmClientError(
            "kLLM is rate limiting requests. Please try again shortly.",
            reason_code="kllm_busy",
        )
    if status == 503:
        return KllmClientError(
            f"kLLM is busy or at capacity for '{model}'. "
            "Please try again in a moment.",
            reason_code="kllm_busy",
        )
    if status >= 500:
        return KllmClientError(
            "kLLM is temporarily unavailable. Please try again later.",
            reason_code="kllm_unavailable",
        )
    return KllmClientError(
        "kLLM rejected the request.",
        reason_code="invalid_request",
    )


def _transport_error(exc: httpx.HTTPError, *, phase: str) -> KllmClientError:
    """Map transport failures without leaking exception text or URLs."""
    if isinstance(exc, httpx.TimeoutException):
        return KllmClientError(
            f"kLLM timed out while {phase}.",
            reason_code="timeout",
        )
    return KllmClientError(
        "Unable to connect to kLLM. Ensure the kLLM relay is reachable.",
        reason_code="kllm_unavailable",
    )


def _stream_error() -> KllmClientError:
    return KllmClientError(
        "kLLM encountered an error while generating a response. Please try again.",
        reason_code="kllm_error",
    )


def _normalized_usage(usage: dict[str, Any]) -> dict[str, Any]:
    """Keep only real token counts supplied by the relay."""
    out: dict[str, Any] = {}
    for src in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cache_read_input_tokens",
    ):
        value = usage.get(src)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[src] = value
    details = usage.get("prompt_tokens_details")
    if isinstance(details, dict):
        cached = details.get("cached_tokens")
        if isinstance(cached, (int, float)) and not isinstance(cached, bool):
            out["cached_tokens"] = cached
    return out


def _normalized_timings(timings: dict[str, Any]) -> dict[str, Any]:
    """Keep only real timing values supplied by llama-server via the relay."""
    mapping = {
        "prompt_n": "prompt_n",
        "prompt_ms": "prompt_ms",
        "prompt_per_second": "prompt_tps",
        "predicted_n": "gen_n",
        "predicted_ms": "gen_ms",
        "predicted_per_second": "gen_tps",
        "cache_n": "cache_n",
    }
    out: dict[str, Any] = {}
    for src, dst in mapping.items():
        value = timings.get(src)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[dst] = value
    return out


class KllmChatClient:
    """Small, focused client for the kLLM chat-completions relay endpoint."""

    def _url(self) -> str:
        return f"{_gateway_base_url()}/v1/chat/completions"

    async def complete(
        self,
        model: str,
        messages: Sequence[dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        timeout: float | None = None,
    ) -> CompletionResult:
        """Execute a non-streaming completion against the kLLM relay."""
        payload = _build_payload(
            model,
            messages,
            stream=False,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
        )
        client = _get_client()
        try:
            response = await client.post(
                self._url(),
                json=payload,
                headers=_request_headers(stream=False),
                timeout=timeout,
            )
        except httpx.HTTPError as exc:
            raise _transport_error(exc, phase="connecting to kLLM") from exc

        if response.status_code >= 400:
            # Drain the body so the pooled connection can be reused, without
            # inspecting or logging its (potentially sensitive) contents.
            await response.aread()
            raise _status_error(response.status_code, model)

        try:
            data = response.json()
        except ValueError as exc:
            raise KllmClientError(
                "kLLM returned an invalid response.",
                reason_code="kllm_error",
            ) from exc
        if not isinstance(data, dict):
            raise KllmClientError(
                "kLLM returned an invalid response.",
                reason_code="kllm_error",
            )
        if data.get("error"):
            raise _stream_error()

        content = ""
        finish_reason: str | None = None
        choices = data.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message") or {}
            if isinstance(message, dict):
                content = message.get("content") or ""
            reason = choices[0].get("finish_reason")
            if isinstance(reason, str):
                finish_reason = reason

        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        timings = data.get("timings") if isinstance(data.get("timings"), dict) else {}
        return CompletionResult(
            content=str(content or ""),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            finish_reason=finish_reason,
            usage=_normalized_usage(usage),
            timings=_normalized_timings(timings),
        )

    async def stream(
        self,
        model: str,
        messages: Sequence[dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
    ) -> AsyncIterator[ContentDelta | StreamMeta]:
        """Stream normalized kLLM events as ``ContentDelta`` / ``StreamMeta``."""
        payload = _build_payload(
            model,
            messages,
            stream=True,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
        )
        client = _get_client()
        try:
            async with client.stream(
                "POST",
                self._url(),
                json=payload,
                headers=_request_headers(stream=True),
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise _status_error(response.status_code, model)

                decoder = SseDecoder()
                async for raw in response.aiter_text():
                    for frame in decoder.feed(raw):
                        for item in _frame_items(frame):
                            yield item
                for frame in decoder.close():
                    for item in _frame_items(frame):
                        yield item
        except KllmClientError:
            raise
        except httpx.HTTPError as exc:
            raise _transport_error(exc, phase="streaming from kLLM") from exc
        # asyncio.CancelledError is deliberately not caught: the ``async with``
        # closes the upstream response so cancellation reaches the relay.


def _frame_items(frame: SseFrame) -> list[ContentDelta | StreamMeta]:
    """Convert one SSE frame into zero or more normalized stream events."""
    if frame.keepalive:
        # Internal liveness signal only: never content, never a finish reason.
        return [StreamMeta("keepalive", {})]

    data = frame.data.strip()
    if not data:
        return []
    if data == "[DONE]":
        # Terminal marker without a reason. A genuine upstream finish_reason
        # arrives in an earlier chunk and must not be overwritten by this.
        return [StreamMeta("end", {})]

    try:
        obj = json.loads(data)
    except (ValueError, TypeError):
        # Malformed frames are ignored; a valid frame follows in practice.
        return []
    if not isinstance(obj, dict):
        return []

    if obj.get("error"):
        raise _stream_error()

    items: list[ContentDelta | StreamMeta] = []
    for choice in obj.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta") or {}
        if not isinstance(delta, dict):
            continue
        content = delta.get("content")
        if isinstance(content, str) and content:
            items.append(ContentDelta(content))
        # Presence only: never forward raw hidden reasoning text.
        if delta.get("reasoning_content"):
            items.append(StreamMeta("status", {"status": "thinking"}))
        reason = choice.get("finish_reason")
        if isinstance(reason, str) and reason:
            items.append(StreamMeta("done", {"finish_reason": reason}))

    usage = obj.get("usage")
    if isinstance(usage, dict) and usage:
        normalized = _normalized_usage(usage)
        if normalized:
            items.append(StreamMeta("usage", normalized))

    timings = obj.get("timings")
    if isinstance(timings, dict) and timings:
        normalized = _normalized_timings(timings)
        if normalized:
            items.append(StreamMeta("timings", normalized))

    # Prefill progress from llama-server (native Chat UI uses the same fields).
    # Presence-gated and numerically validated: never fabricate a percentage.
    progress = obj.get("prompt_progress")
    if isinstance(progress, dict):
        values = {
            key: progress[key]
            for key in ("cache", "processed", "total")
            if isinstance(progress.get(key), (int, float)) and not isinstance(progress.get(key), bool)
        }
        if values:
            items.append(StreamMeta("progress", values))

    # The chunk's model id is authoritative for this response. Never inferred
    # from tags, registry guesses or runtime metadata.
    model = obj.get("model")
    if isinstance(model, str) and model.strip():
        items.append(StreamMeta("model", {"name": model}))

    return items


# Singleton used by the kLLM Chat pathway. Tests monkeypatch its methods.
kllm_chat_client = KllmChatClient()
