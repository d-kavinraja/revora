"""Direct HTTP client for the hosted Ollama OpenAI-compatible endpoint.

This is the transport for the Revora-managed hosted Chat pathway. Ollama speaks
the OpenAI chat-completions protocol at ``/v1/chat/completions``, so the relay
contract is used directly (no LiteLLM provider assumptions):

* ``POST {REVORA_HOSTED_OLLAMA_BASE_URL}/v1/chat/completions``
* the bare Ollama model name, messages, ``stream`` and ``keep_alive`` forwarded;
* server-side bearer token only, never exposed to clients;
* the same tokenized, same-origin gateway login handshake used by every other
  hosted call, for both the streaming and the non-streaming transport;
* stream ``usage`` and neutral status events preserved when the upstream emits
  them. ``reasoning_effort`` is a kLLM/relay concept and is deliberately not
  forwarded to Ollama.

A rejected request (HTTP 400) is classified into a stable reason code
(``prompt_too_long``, ``invalid_message_shape``, ``invalid_option``,
``model_not_found``, ``upstream_rejected_unclassified``). The upstream body is
parsed in memory for classification only and is never returned to a client nor
logged. An unclassified rejection states that the cause is unknown instead of
suggesting the conversation is too long.

Every request holds a global + per-model concurrency permit and (when wake is
enabled) an activity lease; both are released on success, error, timeout and
cancellation. All configuration comes from validated backend settings; no
endpoint or credential is hardcoded into application logic.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import httpx

from app.core.config import keep_alive_is_valid, keep_alive_payload_value, settings
from app.services import hosted_ollama_service
from app.services.hosted_ollama_service import HostedError

from .kllm_client import CompletionResult, ContentDelta, StreamMeta
from .kllm_sse import SseDecoder, SseFrame

logger = logging.getLogger(__name__)


class HostedClientError(HostedError):
    """Safe, client-facing error raised by the hosted transport.

    The message never contains raw upstream payloads, URLs, headers or exception
    details; only a stable ``reason_code`` is surfaced to callers. When the
    upstream rejection was classified, ``structured`` is set so the API layer can
    return ``detail={code, message}`` instead of a bare string.
    """

    def __init__(
        self,
        message: str,
        *,
        reason_code: str | None = None,
        definitive: bool = False,
        structured: bool = False,
        status_code: int | None = None,
    ):
        super().__init__(message, definitive=definitive, reason_code=reason_code)
        self.structured = bool(structured)
        if status_code is not None:
            self.status_code = int(status_code)


def _base_url() -> str:
    try:
        return hosted_ollama_service._validated_base_url()
    except HostedError as exc:
        raise HostedClientError(exc.message, reason_code=exc.reason_code) from exc


def _request_headers(*, stream: bool) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if stream else "application/json",
    }
    token = str(getattr(settings, "REVORA_HOSTED_OLLAMA_TOKEN", "") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _build_payload(
    model: str,
    messages: Sequence[dict[str, Any]],
    *,
    stream: bool,
    max_tokens: int,
    temperature: float | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": list(messages),
        "stream": stream,
        "max_tokens": max_tokens,
        # Keep the served model resident between turns so a follow-up message
        # does not pay a cold load. This never loads a model just to list it.
        # The value is validated at startup; a unitless integer is sent as a
        # JSON number because Ollama parses numbers as seconds and strings with
        # time.ParseDuration (which rejects a bare "-1").
        "keep_alive": keep_alive_payload_value(
            getattr(settings, "REVORA_HOSTED_OLLAMA_KEEP_ALIVE", None)
        ),
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if stream:
        payload["stream_options"] = {"include_usage": True}
    return payload


# Upstream error bodies are bounded and parsed in memory only. Nothing from the
# body is ever returned to a client or logged: it can echo conversation content.
_ERROR_BODY_LIMIT_BYTES = 8_192
_UPSTREAM_CODE_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")

# Structural hints only. A match is recorded as a reason code; the upstream text
# itself never leaves this module.
_PROMPT_TOO_LONG_HINTS = (
    "prompt too long",
    "prompt is too long",
    "context length",
    "context window",
    "context size",
    "exceeds the available context",
    "input length",
    "too many tokens",
    "num_ctx",
    "n_ctx",
)
_MODEL_HINTS = (
    "model not found",
    "no such model",
    "unknown model",
    "model is required",
)
_MESSAGE_SHAPE_HINTS = (
    "messages",
    "message",
    "invalid role",
    "role",
    "tool_call",
    "content",
)
_OPTION_HINTS = (
    # Go's time.ParseDuration wording, which Ollama returns verbatim when it
    # cannot parse keep_alive. Checked before the message-shape hints so a
    # duration error is never mislabelled as a message problem.
    "missing unit in duration",
    "invalid duration",
    "unknown unit",
    "keep_alive",
    "max_tokens",
    "num_predict",
    "temperature",
    "stream_options",
    "option",
)

#: Stable code for an HTTP 400 that no hint list could explain.
UNCLASSIFIED_REJECTION_REASON = "upstream_rejected_unclassified"


def unclassified_rejection_message(upstream_code: str | None) -> str:
    """Safe message for a 400 Revora could not classify.

    Deliberately does NOT claim context exhaustion or any other cause: nothing in
    the response established one. The measured request shape and the upstream
    error type are recorded in the server log.
    """
    detail = f" (upstream type: {upstream_code})" if upstream_code else ""
    return (
        f"Hosted Ollama rejected the request with HTTP 400{detail}. Revora could "
        "not classify the reason, so it is recorded in the server log with the "
        "request shape for diagnosis. Retrying will not help until that is "
        "reviewed."
    )


def _safe_code(value: Any) -> str | None:
    """Return an upstream code/type only when it is a short, plain token."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and _UPSTREAM_CODE_RE.fullmatch(value.strip()):
        return value.strip()
    return None


def _extract_upstream_error(body: bytes) -> tuple[str | None, str | None]:
    """Return ``(code, message)`` from a bounded upstream error body.

    Handles the shapes Ollama emits for a rejected request::

        {"error": {"message": "...", "type": "...", "code": "..."}}
        {"error": "..."}
        {"message": "..."}

    A non-JSON body is treated as a plain message. The result is used for
    classification only; it is never returned to a caller.
    """
    if not body:
        return None, None
    text = body[:_ERROR_BODY_LIMIT_BYTES].decode("utf-8", "replace").strip()
    if not text:
        return None, None
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return None, text
    if not isinstance(obj, dict):
        return None, None
    code = _safe_code(obj.get("type")) or _safe_code(obj.get("code"))
    error = obj.get("error")
    if isinstance(error, dict):
        return (
            _safe_code(error.get("code")) or _safe_code(error.get("type")) or code,
            str(error["message"]) if isinstance(error.get("message"), str) else None,
        )
    if isinstance(error, str):
        return code, error
    message = obj.get("message")
    if isinstance(message, str):
        return code, message
    return code, None


def _classify_upstream_rejection(
    message: str | None, *, upstream_code: str | None = None
) -> tuple[str, str, str | None]:
    """Map an upstream message onto a stable reason code and a safe message.

    Returns ``(reason_code, safe_message, matched_hint)``. ``matched_hint`` is the
    keyword that matched (a constant from this module), never upstream text. When
    nothing matches, the code is ``upstream_rejected_unclassified`` and the
    message states plainly that the cause is unknown; it never blames context.
    """
    lowered = (message or "").lower()
    for hint in _PROMPT_TOO_LONG_HINTS:
        if hint in lowered:
            return (
                "prompt_too_long",
                "The conversation is longer than the hosted model can accept. "
                "Start a new chat or shorten your last message and try again.",
                hint,
            )
    for hint in _MODEL_HINTS:
        if hint in lowered:
            return (
                "model_not_found",
                "The selected model is no longer available on the hosted runtime.",
                hint,
            )
    for hint in _OPTION_HINTS:
        if hint in lowered:
            return (
                "invalid_option",
                "Hosted Ollama rejected a request option (for example "
                "keep_alive or max_tokens). Please try again.",
                hint,
            )
    for hint in _MESSAGE_SHAPE_HINTS:
        if hint in lowered:
            return (
                "invalid_message_shape",
                "Hosted Ollama rejected the message format. Clear this chat and "
                "send the message again.",
                hint,
            )
    return (
        UNCLASSIFIED_REJECTION_REASON,
        unclassified_rejection_message(upstream_code),
        None,
    )


def _prompt_stats(messages: Sequence[dict[str, Any]]) -> tuple[int, int]:
    """Return ``(message_count, total_chars)`` for the outgoing user/assistant turns."""
    count = 0
    chars = 0
    for message in messages or ():
        if not isinstance(message, dict):
            continue
        if message.get("role") not in ("user", "assistant"):
            continue
        count += 1
        content = message.get("content")
        if isinstance(content, str):
            chars += len(content)
    return count, chars


def _final_role(messages: Sequence[dict[str, Any]]) -> str:
    """Return the role of the final message, for redacted diagnostics only."""
    for message in reversed(list(messages or ())):
        if isinstance(message, dict) and isinstance(message.get("role"), str):
            return message["role"][:16]
    return "none"


def _keep_alive_ok() -> bool:
    """Whether the configured keep_alive currently passes validation."""
    return keep_alive_is_valid(getattr(settings, "REVORA_HOSTED_OLLAMA_KEEP_ALIVE", None))


async def _read_error_body(response: httpx.Response) -> bytes:
    try:
        return await response.aread()
    except Exception:  # pragma: no cover - defensive, body is best-effort
        return b""


def _invalid_request_error(
    model: str,
    *,
    body: bytes,
    message_count: int,
    total_chars: int,
    max_tokens: int,
    path: str,
    context_window: int | None = None,
    last_role: str | None = None,
) -> HostedClientError:
    """Classify a hosted HTTP 400 without exposing the upstream body."""
    upstream_code, upstream_message = _extract_upstream_error(body)
    reason_code, safe_message, matched_hint = _classify_upstream_rejection(
        upstream_message, upstream_code=upstream_code
    )
    # Redacted diagnostics: request shape, a stable reason code and an
    # allow-listed upstream code. Never the prompt, the response, the URL, a
    # cookie, an authorization header or the raw body.
    logger.warning(
        "hosted_upstream_rejected model=%s status=400 reason=%s path=%s messages=%s "
        "chars=%s est_tokens=%s output_budget=%s context_window=%s final_role=%s "
        "upstream_code=%s upstream_bytes=%s matched_hint=%s keep_alive_ok=%s",
        model,
        reason_code,
        path,
        message_count,
        total_chars,
        (total_chars + 3) // 4,
        max_tokens,
        context_window if context_window is not None else "unknown",
        last_role or "unknown",
        upstream_code or "unknown",
        len(body or b""),
        matched_hint or "none",
        _keep_alive_ok(),
    )
    return HostedClientError(
        safe_message, reason_code=reason_code, structured=True, status_code=400
    )


def _status_error(status: int, model: str) -> HostedClientError:
    if status in (401, 403):
        return HostedClientError(
            "Hosted Ollama rejected the server credentials.",
            reason_code="hosted_auth_error",
        )
    if status == 404:
        return HostedClientError(
            f"Model '{model}' was not found on the hosted runtime.",
            reason_code="model_not_found",
        )
    # HTTP 400 is never handled here: the caller classifies it from the upstream
    # body via _invalid_request_error(), which is the single authoritative 400
    # path. Keeping a duplicate branch here would emit a message that hides the
    # real reason.
    if status == 429:
        return HostedClientError(
            "Hosted Ollama is rate limiting requests. Please try again shortly.",
            reason_code="hosted_busy",
        )
    if status == 503:
        return HostedClientError(
            f"Hosted Ollama is busy or at capacity for '{model}'. "
            "Please try again in a moment.",
            reason_code="hosted_busy",
        )
    if status >= 500:
        return HostedClientError(
            "Hosted Ollama is temporarily unavailable. Please try again later.",
            reason_code="hosted_unavailable",
        )
    return HostedClientError(
        "Hosted Ollama rejected the request.", reason_code="invalid_request"
    )


def _transport_error(exc: httpx.HTTPError, *, phase: str) -> HostedClientError:
    if isinstance(exc, httpx.TimeoutException):
        return HostedClientError(
            f"Hosted Ollama timed out while {phase}.", reason_code="timeout"
        )
    return HostedClientError(
        "Unable to connect to hosted Ollama. Ensure the hosted runtime is reachable.",
        reason_code="hosted_unavailable",
    )


def _stream_error() -> HostedClientError:
    return HostedClientError(
        "Hosted Ollama encountered an error while generating a response. Please try again.",
        reason_code="hosted_error",
    )


def _normalized_usage(usage: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for src in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(src)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[src] = value
    return out


CHAT_COMPLETIONS_PATH = "/v1/chat/completions"


@asynccontextmanager
async def _gateway_stream(
    url: str,
    *,
    payload: dict[str, Any],
    headers: dict[str, str],
) -> AsyncIterator[httpx.Response]:
    """Open a streamed POST, completing the private-port gateway login.

    The non-streaming path reuses ``hosted_ollama_service
    ._request_with_gateway_login``. That helper buffers the whole response, so it
    cannot serve a live stream and this is the streaming equivalent of it.

    The tokenized URL may answer with a same-origin redirect plus a cookie, in
    which case the request is repeated against the resolved same-origin target
    and relies on the shared client's cookie jar, exactly like discovery does.
    The redirect body is never read, and the redirect target is resolved by the
    shared ``same_origin_redirect_target`` helper so cross-origin hops are
    refused and SSRF protection is preserved. Streaming, timeouts, cancellation
    and concurrency permits are unchanged: the permits are held by the caller and
    the response is closed when the caller's block exits, exactly as
    ``client.stream`` would.
    """
    client = hosted_ollama_service._get_client()
    async with client.stream("POST", url, json=payload, headers=headers) as response:
        target = hosted_ollama_service.same_origin_redirect_target(response)
        if target is None:
            yield response
            return
    async with client.stream("POST", target, json=payload, headers=headers) as response:
        yield response


class HostedOllamaClient:
    """Small, focused client for the hosted Ollama chat-completions endpoint."""

    def _url(self) -> str:
        return hosted_ollama_service.endpoint_url("/v1/chat/completions")

    async def complete(
        self,
        model: str,
        messages: Sequence[dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float | None = None,
        timeout: float | None = None,
        context_window: int | None = None,
    ) -> CompletionResult:
        payload = _build_payload(
            model, messages, stream=False, max_tokens=max_tokens, temperature=temperature
        )
        async with hosted_ollama_service.permit(model):
            async with hosted_ollama_service.activity_lease():
                try:
                    # Reuses the service helper so inference gets the same
                    # tokenized same-origin gateway handshake as every other
                    # hosted call (discovery/show/version).
                    response, redirect_error = (
                        await hosted_ollama_service._request_with_gateway_login(
                            "POST",
                            CHAT_COMPLETIONS_PATH,
                            timeout=timeout,
                            payload=payload,
                            headers=_request_headers(stream=False),
                        )
                    )
                except httpx.HTTPError as exc:
                    raise _transport_error(exc, phase="connecting to hosted Ollama") from exc

                if response is None:
                    raise HostedClientError(
                        redirect_error
                        or "Unable to connect to hosted Ollama. "
                        "Ensure the hosted runtime is reachable.",
                        reason_code="hosted_unavailable",
                    )

                if response.status_code >= 400:
                    body = await _read_error_body(response)
                    if response.status_code == 400:
                        count, chars = _prompt_stats(messages)
                        raise _invalid_request_error(
                            model,
                            body=body,
                            message_count=count,
                            total_chars=chars,
                            max_tokens=max_tokens,
                            path="complete",
                            context_window=context_window,
                            last_role=_final_role(messages),
                        )
                    raise _status_error(response.status_code, model)

                try:
                    data = response.json()
                except ValueError as exc:
                    raise HostedClientError(
                        "Hosted Ollama returned an invalid response.",
                        reason_code="hosted_error",
                    ) from exc
                if not isinstance(data, dict):
                    raise HostedClientError(
                        "Hosted Ollama returned an invalid response.",
                        reason_code="hosted_error",
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
                return CompletionResult(
                    content=str(content or ""),
                    prompt_tokens=int(usage.get("prompt_tokens") or 0),
                    completion_tokens=int(usage.get("completion_tokens") or 0),
                    finish_reason=finish_reason,
                    usage=_normalized_usage(usage),
                    timings={},
                )

    async def stream(
        self,
        model: str,
        messages: Sequence[dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float | None = None,
        context_window: int | None = None,
    ) -> AsyncIterator[ContentDelta | StreamMeta]:
        payload = _build_payload(
            model, messages, stream=True, max_tokens=max_tokens, temperature=temperature
        )
        async with hosted_ollama_service.permit(model):
            async with hosted_ollama_service.activity_lease():
                try:
                    async with _gateway_stream(
                        self._url(),
                        payload=payload,
                        headers=_request_headers(stream=True),
                    ) as response:
                        if response.status_code >= 400:
                            body = await _read_error_body(response)
                            if response.status_code == 400:
                                count, chars = _prompt_stats(messages)
                                raise _invalid_request_error(
                                    model,
                                    body=body,
                                    message_count=count,
                                    total_chars=chars,
                                    max_tokens=max_tokens,
                                    path="stream",
                                    context_window=context_window,
                                    last_role=_final_role(messages),
                                )
                            raise _status_error(response.status_code, model)

                        decoder = SseDecoder()
                        async for raw in response.aiter_text():
                            for frame in decoder.feed(raw):
                                for item in _frame_items(frame):
                                    yield item
                        for frame in decoder.close():
                            for item in _frame_items(frame):
                                yield item
                except HostedClientError:
                    raise
                except httpx.HTTPError as exc:
                    raise _transport_error(exc, phase="streaming from hosted Ollama") from exc
                # asyncio.CancelledError is deliberately not caught: the context
                # managers close the upstream response and release the permit and
                # lease so cancellation reaches the runtime.


def _frame_items(frame: SseFrame) -> list[ContentDelta | StreamMeta]:
    if frame.keepalive:
        return [StreamMeta("keepalive", {})]
    data = frame.data.strip()
    if not data:
        return []
    if data == "[DONE]":
        return [StreamMeta("end", {})]
    try:
        obj = json.loads(data)
    except (ValueError, TypeError):
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
        if delta.get("reasoning_content") or delta.get("thinking"):
            items.append(StreamMeta("status", {"status": "thinking"}))
        reason = choice.get("finish_reason")
        if isinstance(reason, str) and reason:
            items.append(StreamMeta("done", {"finish_reason": reason}))

    usage = obj.get("usage")
    if isinstance(usage, dict) and usage:
        normalized = _normalized_usage(usage)
        if normalized:
            items.append(StreamMeta("usage", normalized))

    model = obj.get("model")
    if isinstance(model, str) and model.strip():
        items.append(StreamMeta("model", {"name": model}))

    return items


# Singleton used by the hosted Chat pathway. Tests monkeypatch its methods.
hosted_ollama_client = HostedOllamaClient()


async def aclose() -> None:
    await hosted_ollama_service.aclose()
