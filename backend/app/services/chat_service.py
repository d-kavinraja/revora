"""Temporary kLLM chat orchestration.

This module enforces chat-specific limits and provides SSE streaming without
persisting prompts, responses, or chat metadata.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from time import monotonic
from typing import Any

from fastapi import HTTPException, Request

from app.ai.kllm_client import StreamMeta
from app.ai.llm import llm_service
from app.security.content_guard import sanitize_input
from app.services.kllm_service import KllmError

logger = logging.getLogger(__name__)

MAX_MESSAGES = 20
MAX_CONTEXT_CHARS = 240_000
# Safety ceiling for a single message payload. Real capacity is further bounded by
# the selected model context window and gateway/runtime limits.
MAX_MESSAGE_CHARS = 200_000
MAX_REQUEST_MESSAGES = 40
# Output budget is derived from the resolved model context window instead of a
# flat small default. The ceiling is bounded: a 128K/256K model still gets a
# generous but finite generation budget, and reasoning effort (which shares the
# same budget in the relay) cannot consume an unbounded amount.
MAX_OUTPUT_TOKENS = 16_384
DEFAULT_OUTPUT_TOKENS = 4_096  # conservative fallback when context is unknown
MIN_OUTPUT_TOKENS = 1_024      # target floor, never forced past remaining context
OUTPUT_CONTEXT_RESERVE = 2_048  # headroom for KV cache / concurrent slots
CHARS_PER_TOKEN_ESTIMATE = 4    # documented approximation, not an exact count
RATE_LIMIT_REQUESTS = 20
RATE_LIMIT_WINDOW_SECONDS = 60
SINGLE_FLIGHT_TTL_SECONDS = 15 * 60
FIRST_TOKEN_TIMEOUT_SECONDS = 90
IDLE_TIMEOUT_SECONDS = 60
TOTAL_TIMEOUT_SECONDS = 600

STREAM_HEADERS = {
    # `no-transform` is required for live streaming: the reverse proxy in front
    # of the app compresses text/event-stream responses, and zlib buffers small
    # SSE frames until the stream ends, so the browser only sees the answer at
    # completion. This directive makes intermediaries forward frames untouched.
    "Cache-Control": "no-store, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@dataclass
class _UserRateState:
    hits: deque[float]
    active_until: float = 0.0


_rate_state: dict[str, _UserRateState] = {}
_rate_lock = asyncio.Lock()


def reset_chat_runtime_state() -> None:
    """Test-only helper to clear in-process rate/single-flight state."""
    _rate_state.clear()


def estimate_input_tokens(messages: list[dict[str, str]]) -> int:
    """Approximate the trimmed prompt size (~4 chars/token).

    No tokenizer is available in this pathway. This is a conservative estimate
    used only for budget arithmetic; it is never reported as an exact count.
    """
    chars = sum(len(str(msg.get("content") or "")) for msg in messages)
    return (chars + CHARS_PER_TOKEN_ESTIMATE - 1) // CHARS_PER_TOKEN_ESTIMATE


def resolve_max_tokens(
    requested: int | None,
    context_window: int | None,
    messages: list[dict[str, str]],
) -> int:
    """Resolve a bounded, context-aware generation budget.

    An explicit ``requested`` value is honoured but clamped to the safe remaining
    context and the global ceiling. With no override, the target is the whole
    usable context (floored at ``MIN_OUTPUT_TOKENS``), then clamped. If the
    remaining context is below that floor it is NOT raised back up: the smaller
    safe value is returned so the request never exceeds the model's capacity.
    """
    if not context_window or context_window <= 0:
        target = requested if requested is not None else DEFAULT_OUTPUT_TOKENS
        return max(1, min(target, MAX_OUTPUT_TOKENS))

    input_tokens = estimate_input_tokens(messages)
    usable = context_window - input_tokens - OUTPUT_CONTEXT_RESERVE
    target = requested if requested is not None else max(MIN_OUTPUT_TOKENS, usable)
    return max(1, min(target, usable, MAX_OUTPUT_TOKENS))


def safe_chat_error(exc: Exception, *, display_model: str | None = None) -> tuple[str, str]:
    if isinstance(exc, HTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "Chat request failed."
        return "chat_error", detail
    if isinstance(exc, KllmError):
        return exc.reason_code or "kllm_error", exc.message
    if isinstance(exc, asyncio.TimeoutError):
        model_text = f" for '{display_model}'" if display_model else ""
        return "timeout", f"kLLM timed out while serving{model_text}."
    message = llm_service._managed_error_message(exc, display_model or "model")
    lower = message.lower()
    if "busy" in lower or "capacity" in lower:
        return "kllm_busy", message
    if "timed out" in lower or "timeout" in lower:
        return "timeout", message
    if "connect" in lower:
        return "kllm_unavailable", message
    if "not found" in lower:
        return "model_not_found", message
    if "credentials" in lower:
        return "kllm_auth_error", message
    return "kllm_error", message


async def enforce_chat_limits(user_id: str) -> None:
    now = monotonic()
    async with _rate_lock:
        state = _rate_state.get(user_id)
        if state is None:
            state = _UserRateState(hits=deque())
            _rate_state[user_id] = state

        window_start = now - RATE_LIMIT_WINDOW_SECONDS
        while state.hits and state.hits[0] < window_start:
            state.hits.popleft()

        if len(state.hits) >= RATE_LIMIT_REQUESTS:
            raise HTTPException(
                status_code=429,
                detail="You're sending messages too quickly. Please wait a moment and try again.",
            )
        if state.active_until > now:
            raise HTTPException(
                status_code=429,
                detail="A response is already being generated. Stop it before sending another message.",
            )

        state.hits.append(now)
        state.active_until = now + SINGLE_FLIGHT_TTL_SECONDS

        stale_before = now - (RATE_LIMIT_WINDOW_SECONDS * 2)
        stale_users = [
            uid
            for uid, item in _rate_state.items()
            if (not item.hits or item.hits[-1] < stale_before) and item.active_until < now
        ]
        for uid in stale_users:
            _rate_state.pop(uid, None)


async def release_chat_single_flight(user_id: str) -> None:
    async with _rate_lock:
        state = _rate_state.get(user_id)
        if state is not None:
            state.active_until = 0.0


def trim_chat_context(messages: list[Any]) -> list[dict[str, str]]:
    trimmed = list(messages[-MAX_MESSAGES:])
    prepared: list[dict[str, str]] = []
    total_chars = 0

    for msg in reversed(trimmed):
        role = getattr(msg, "role", None) if not isinstance(msg, dict) else msg.get("role")
        content_raw = (
            getattr(msg, "content", None) if not isinstance(msg, dict) else msg.get("content")
        )
        if role not in {"user", "assistant"}:
            continue
        content = sanitize_input(str(content_raw or "").strip())
        if not content:
            continue
        content_len = len(content)
        if prepared and total_chars + content_len > MAX_CONTEXT_CHARS:
            break
        if not prepared and content_len > MAX_CONTEXT_CHARS:
            content = content[-MAX_CONTEXT_CHARS:]
            content_len = len(content)
        prepared.append({"role": role, "content": content})
        total_chars += content_len
        if total_chars >= MAX_CONTEXT_CHARS:
            break

    prepared.reverse()
    while prepared and prepared[0]["role"] != "user":
        prepared.pop(0)
    return prepared


def sse_event(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"


async def stream_chat_sse(
    http_request: Request,
    *,
    user_id: str,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float | None,
    reasoning_effort: str | None = None,
) -> AsyncIterator[str]:
    start = monotonic()
    last_event = start
    emitted = False
    finish_reason = "stop"
    ait = None
    try:
        stream = llm_service.stream_managed_completion(
            model,
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
        )
        ait = stream.__aiter__()
        while True:
            if await http_request.is_disconnected():
                logger.info(
                    "chat_stream_disconnected model=%s messages=%s chars=%s",
                    model,
                    len(messages),
                    sum(len(m.get("content", "")) for m in messages),
                )
                return

            # Absolute deadline from the fixed start: never reset by keepalives.
            remaining_total = TOTAL_TIMEOUT_SECONDS - (monotonic() - start)
            if remaining_total <= 0:
                raise TimeoutError()

            timeout = min(
                IDLE_TIMEOUT_SECONDS if emitted else FIRST_TOKEN_TIMEOUT_SECONDS,
                remaining_total,
            )
            try:
                item = await asyncio.wait_for(ait.__anext__(), timeout=timeout)
            except StopAsyncIteration:
                break

            # Every item — including an internal keepalive — proves the upstream
            # is alive and restarts the wait_for window above. Only visible
            # content flips `emitted`, so genuine prefill keepalives keep the
            # first-token deadline from firing on a healthy, silent prefill.
            last_event = monotonic()
            if isinstance(item, StreamMeta):
                if item.kind == "keepalive":
                    # Relay prefill comment: internal liveness only. Never sent
                    # to the client, never content, never a finish reason.
                    continue
                if item.kind == "end":
                    # [DONE] terminal marker carries no reason. Leave the actual
                    # upstream finish_reason (e.g. "length") untouched.
                    continue
                if item.kind == "usage" and item.data:
                    yield sse_event({"type": "usage", **item.data})
                elif item.kind == "timings" and item.data:
                    yield sse_event({"type": "timings", **item.data})
                elif item.kind == "status" and item.data:
                    yield sse_event({"type": "status", **item.data})
                elif item.kind == "progress" and item.data:
                    # Prefill telemetry: non-content, never changes completion.
                    yield sse_event({"type": "progress", **item.data})
                elif item.kind == "model" and item.data:
                    # Authoritative model id for this response; non-terminal.
                    yield sse_event({"type": "model", **item.data})
                elif item.kind == "done":
                    reason = item.data.get("finish_reason")
                    if isinstance(reason, str) and reason:
                        finish_reason = reason
                continue

            delta = str(item)
            if not delta:
                continue
            emitted = True
            yield sse_event({"type": "delta", "content": delta})

        yield sse_event({"type": "done", "finish_reason": finish_reason})
        logger.info(
            "chat_stream_complete model=%s messages=%s chars=%s duration_ms=%s emitted=%s",
            model,
            len(messages),
            sum(len(m.get("content", "")) for m in messages),
            int((monotonic() - start) * 1000),
            emitted,
        )
    except asyncio.CancelledError:
        logger.info(
            "chat_stream_cancelled model=%s messages=%s duration_ms=%s",
            model,
            len(messages),
            int((monotonic() - start) * 1000),
        )
        raise
    except Exception as exc:
        code, message = safe_chat_error(exc, display_model=model)
        logger.warning(
            "chat_stream_error model=%s code=%s error_type=%s duration_ms=%s idle_ms=%s",
            model,
            code,
            type(exc).__name__,
            int((monotonic() - start) * 1000),
            int((monotonic() - last_event) * 1000),
        )
        yield sse_event({"type": "error", "code": code, "message": message})
    finally:
        aclose = getattr(ait, "aclose", None)
        if callable(aclose):
            try:
                await aclose()
            except Exception:
                pass
        await release_chat_single_flight(user_id)
