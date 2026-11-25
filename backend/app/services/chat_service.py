"""Temporary kLLM chat orchestration.

This module enforces chat-specific limits and provides SSE streaming without
persisting prompts, responses, or chat metadata.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, Request

from app.ai.kllm_client import StreamMeta
from app.ai.llm import llm_service
from app.core.config import settings
from app.security.content_guard import sanitize_input
from app.services.hosted_ollama_service import HostedError
from app.services.kllm_service import KllmError

logger = logging.getLogger(__name__)

# Fixed fallbacks, used only when the selected model's context window is unknown.
MAX_MESSAGES = 20
MAX_CONTEXT_CHARS = 240_000
# Provider-independent conversation ceilings. A model with a large window may
# receive the whole conversation, never more than this.
MAX_CONTEXT_MESSAGES_GLOBAL = 200
MAX_CONTEXT_CHARS_GLOBAL = 1_200_000
# Safety ceiling for a single message payload. Real capacity is further bounded by
# the selected model context window and gateway/runtime limits.
MAX_MESSAGE_CHARS = 200_000
# Wire ceiling: one per-chat history holds at most MAX_CONTEXT_MESSAGES_GLOBAL
# turns, so a client can never send a conversation the store could not hold.
MAX_REQUEST_MESSAGES = MAX_CONTEXT_MESSAGES_GLOBAL
MAX_REQUEST_CHARS = MAX_CONTEXT_CHARS_GLOBAL
# Output budget is derived from the resolved model context window instead of a
# flat small default. The ceiling is bounded: a 128K/256K model still gets a
# generous but finite generation budget, and reasoning effort (which shares the
# same budget in the relay) cannot consume an unbounded amount.
MAX_OUTPUT_TOKENS = 16_384
DEFAULT_OUTPUT_TOKENS = 4_096  # conservative fallback when context is unknown
MIN_OUTPUT_TOKENS = 1_024      # target floor, never forced past remaining context
OUTPUT_CONTEXT_RESERVE = 2_048  # headroom for KV cache / concurrent slots
CHARS_PER_TOKEN_ESTIMATE = 4    # documented approximation, not an exact count
# Conservative characters-per-token used to fit a prompt to a real window.
# The relay budgets roughly ``len(body) / 3.2``, so 3 cannot over-admit.
CHARS_PER_TOKEN_FIT = 3
# Smallest prompt allowance considered useful. A client-supplied max_tokens is
# clamped so at least this much input still fits, instead of collapsing a real
# conversation to a one-character prompt.
MIN_INPUT_TOKENS = 512
# Outbound-only marker inserted when one turn is too large for the window. The
# stored message is never modified; exactly one marker is created per request,
# so it can never accumulate across turns.
CLIP_MARKER = "\n\n[... clipped to fit the model context ...]\n\n"
# Share of the room given to the beginning of an oversized turn. The beginning
# carries the instruction/question, so it keeps the larger share.
CLIP_HEAD_SHARE = 0.6
# Reported when a stream ended cleanly without ever signalling a terminal
# completion reason: the answer may be incomplete and must not read as "stop".
INCOMPLETE_FINISH_REASON = "incomplete"
RATE_LIMIT_REQUESTS = 20
RATE_LIMIT_WINDOW_SECONDS = 60
# Generic refusal for both a duplicate chat and the per-user cap. The client
# never learns which one fired, but the wording still tells it to stop the
# running answer.
CHAT_BUSY_MESSAGE = (
    "A response is already being generated. Stop it before sending another message."
)
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


# One admitted generation, owned by exactly one user request.
# ``chat_id`` is the optional client chat identifier: when present it makes
# the lease single-flight for that chat, when absent two anonymous chats of
# the same user are allowed (backward compatible with older clients).
@dataclass(frozen=True)
class ChatLease:
    lease_id: str
    user_id: str
    chat_id: str | None
    expires_at: float


_rate_state: dict[str, _UserRateState] = {}
_rate_lock = asyncio.Lock()
# Owner-scoped lease registry. A lease is keyed by its opaque id and indexed
# per user, so a release can only ever free the exact generation that took
# it: a late callback from a stopped stream can never clear a newer stream.
_chat_leases: dict[str, ChatLease] = {}
_user_leases: dict[str, set[str]] = {}


def reset_chat_runtime_state() -> None:
    """Test-only helper to clear in-process rate and lease state."""
    _rate_state.clear()
    _chat_leases.clear()
    _user_leases.clear()


def estimate_input_tokens(messages: list[dict[str, str]]) -> int:
    """Approximate the trimmed prompt size in tokens.

    No tokenizer is available in this pathway. The same conservative
    ``CHARS_PER_TOKEN_FIT`` ratio that fits the prompt is used here, so the
    fitted prompt, the permitted output and the safety headroom are expressed
    in one unit and cannot silently over-commit the window.
    """
    chars = sum(len(str(msg.get("content") or "")) for msg in messages)
    return (chars + CHARS_PER_TOKEN_FIT - 1) // CHARS_PER_TOKEN_FIT


def resolve_max_tokens(
    requested: int | None,
    context_window: int | None,
    messages: list[dict[str, str]],
) -> int:
    """Resolve a bounded, context-aware generation budget.

    An explicit ``requested`` value is honoured but clamped to the safe remaining
    context, the output reserve and the global ceiling. With no override, the
    target is the smaller of the conservative default and the window reserve.
    Every bound is computed with the same chars/token ratio used to fit the
    prompt, so prompt + output + headroom can never exceed the window.
    """
    if not context_window or context_window <= 0:
        target = requested if requested is not None else DEFAULT_OUTPUT_TOKENS
        return max(1, min(target, MAX_OUTPUT_TOKENS))

    input_tokens = estimate_input_tokens(messages)
    headroom = output_safety_headroom(context_window)
    remaining = context_window - input_tokens - headroom
    reserve = hosted_output_reserve(requested, context_window)
    target = requested if requested is not None else min(DEFAULT_OUTPUT_TOKENS, reserve)
    allowed = min(target, reserve, max(1, remaining))
    return max(1, min(allowed, MAX_OUTPUT_TOKENS))


def safe_chat_error(exc: Exception, *, display_model: str | None = None) -> tuple[str, str]:
    if isinstance(exc, HTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "Chat request failed."
        return "chat_error", detail
    if isinstance(exc, HostedError):
        return exc.reason_code or "hosted_error", exc.message
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


def _drop_lease(lease_id: str) -> None:
    lease = _chat_leases.pop(lease_id, None)
    if lease is None:
        return
    owned = _user_leases.get(lease.user_id)
    if owned is not None:
        owned.discard(lease_id)
        if not owned:
            _user_leases.pop(lease.user_id, None)


def _reap_expired_leases(now: float) -> int:
    expired = [
        lease_id
        for lease_id, lease in _chat_leases.items()
        if lease.expires_at <= now
    ]
    for lease_id in expired:
        _drop_lease(lease_id)
    return len(expired)


async def acquire_chat_lease(user_id: str, chat_id: str | None = None) -> ChatLease:
    """Admit one generation for ``user_id``, or raise the generic 429.

    Admission is bounded: a duplicate ``chat_id`` of the same user is refused,
    and so is any request beyond the configured per-user concurrency cap. The
    cap is per user, so two users can always run their own chats in parallel.
    """
    now = monotonic()
    # Expired leases are recovered lazily, so a crashed worker can never keep
    # capacity reserved for longer than the configured TTL.
    _reap_expired_leases(now)
    owned = _user_leases.get(user_id)
    if owned:
        if chat_id is not None:
            for lease_id in owned:
                if _chat_leases[lease_id].chat_id == chat_id:
                    raise HTTPException(status_code=429, detail=CHAT_BUSY_MESSAGE)
        if len(owned) >= settings.CHAT_MAX_CONCURRENT_REQUESTS_PER_USER:
            raise HTTPException(status_code=429, detail=CHAT_BUSY_MESSAGE)
    lease = ChatLease(
        lease_id=uuid4().hex,
        user_id=user_id,
        chat_id=chat_id,
        expires_at=now + settings.CHAT_LEASE_TTL_SECONDS,
    )
    _chat_leases[lease.lease_id] = lease
    _user_leases.setdefault(user_id, set()).add(lease.lease_id)
    return lease


async def touch_chat_lease(lease: ChatLease) -> bool:
    """Extend a live lease, but only when it is still the current one."""
    current = _chat_leases.get(lease.lease_id)
    if current != lease:
        return False
    _chat_leases[lease.lease_id] = ChatLease(
        lease_id=lease.lease_id,
        user_id=lease.user_id,
        chat_id=lease.chat_id,
        expires_at=monotonic() + settings.CHAT_LEASE_TTL_SECONDS,
    )
    return True


async def release_chat_lease(lease: ChatLease) -> bool:
    """Release ``lease`` only when this request still owns it.

    Owner-scoped and idempotent: a missing, expired, superseded or foreign
    lease is a no-op, so duplicate cleanup can never free a newer generation.
    """
    current = _chat_leases.get(lease.lease_id)
    if current is None:
        return False
    if current.user_id != lease.user_id or current.chat_id != lease.chat_id:
        return False
    _drop_lease(lease.lease_id)
    return True


async def reap_expired_chat_leases(now: float | None = None) -> int:
    """Drop every lease past its expiry; returns how many were recovered."""
    return _reap_expired_leases(monotonic() if now is None else now)


async def release_chat_single_flight(user_id: str) -> int:
    """Deprecated best-effort cleanup: release every lease of one user."""
    released = 0
    for lease_id in list(_user_leases.get(user_id, ())):
        _drop_lease(lease_id)
        released += 1
    return released


def _prune_rate_state(now: float) -> None:
    stale_before = now - (RATE_LIMIT_WINDOW_SECONDS * 2)
    for uid, item in list(_rate_state.items()):
        if uid in _user_leases:
            continue
        if not item.hits or item.hits[-1] < stale_before:
            _rate_state.pop(uid, None)


async def enforce_chat_limits(user_id: str, chat_id: str | None = None) -> ChatLease:
    """Apply the per-user rate limit, then admit one leased generation."""
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
    # The lease is taken before the rate hit is recorded, so a request refused
    # for concurrency does not consume the user's rate budget.
    lease = await acquire_chat_lease(user_id, chat_id)
    async with _rate_lock:
        _rate_state.setdefault(user_id, _UserRateState(hits=deque())).hits.append(now)
    _prune_rate_state(now)
    return lease


def output_safety_headroom(context_window: int | None) -> int:
    """Headroom kept free for provider overhead and estimator error."""
    if not context_window or context_window <= 0:
        return OUTPUT_CONTEXT_RESERVE
    # A tiny window cannot afford the full reserve or nothing would be left.
    if context_window < OUTPUT_CONTEXT_RESERVE * 4:
        return min(OUTPUT_CONTEXT_RESERVE, max(0, int(context_window) // 4))
    return OUTPUT_CONTEXT_RESERVE


def max_output_tokens_for_window(context_window: int | None) -> int:
    """Largest generation budget that still leaves a usable prompt allowance."""
    if not context_window or context_window <= 0:
        return MAX_OUTPUT_TOKENS
    room = int(context_window) - output_safety_headroom(context_window) - MIN_INPUT_TOKENS
    return max(1, min(room, MAX_OUTPUT_TOKENS))


def clamp_requested_max_tokens(
    requested: int | None, context_window: int | None
) -> int | None:
    """Clamp a client override so a real prompt still fits next to it."""
    if requested is None:
        return None
    return max(1, min(int(requested), max_output_tokens_for_window(context_window)))


def clip_to_budget(content: str, max_chars: int) -> str:
    """Clip one oversized turn, keeping its beginning and its end.

    Blindly keeping the tail of a large newest turn drops the instruction and
    leaves the model answering an anonymous excerpt. The beginning therefore
    keeps the larger share, and the end is kept as well because pasted code and
    error output usually finish with the part being asked about. The marker is
    outbound-only, so stored history is never rewritten, and exactly one marker
    is present even when the source already contained one.
    """
    if max_chars <= len(CLIP_MARKER) + 8:
        # Too small for a marker: keep the instruction rather than nothing.
        return content[: max(0, max_chars)]
    if len(content) <= max_chars:
        return content
    body = content.replace(CLIP_MARKER, "\n")
    room = max(1, max_chars - len(CLIP_MARKER))
    head_len = max(1, int(room * CLIP_HEAD_SHARE))
    tail_len = max(0, room - head_len)
    head = body[:head_len]
    tail = body[-tail_len:] if tail_len else ""
    return f"{head}{CLIP_MARKER}{tail}"


def context_fit_budget(
    context_window: int | None,
    requested_max_tokens: int | None = None,
) -> tuple[int, int]:
    """Return ``(max_messages, max_chars)`` for one provider request.

    The reserve for generated output is taken out of the window first, then the
    same safety headroom that bounds the generation budget, and only the
    remainder is offered to the prompt. One chars-per-token ratio is used for
    fitting and for estimating, so prompt + output + headroom add up inside the
    window instead of over-committing it.

    Without a known window the fixed legacy caps apply, so an unresolved model
    can never receive an unbounded prompt.
    """
    if not context_window or context_window <= 0:
        return MAX_MESSAGES, MAX_CONTEXT_CHARS
    reserve = hosted_output_reserve(requested_max_tokens, context_window)
    input_tokens = max(0, int(context_window) - reserve - output_safety_headroom(context_window))
    max_chars = min(MAX_CONTEXT_CHARS_GLOBAL, input_tokens * CHARS_PER_TOKEN_FIT)
    return MAX_CONTEXT_MESSAGES_GLOBAL, max(1, max_chars)


def trim_chat_context(
    messages: list[Any],
    *,
    strict_alternation: bool = False,
    context_window: int | None = None,
    requested_max_tokens: int | None = None,
) -> list[dict[str, str]]:
    """Fit a conversation to the selected model's real input budget.

    The budget comes from the ready model's own context window, so a large
    window receives the whole conversation instead of an arbitrary 20 turns.
    Whole oldest turns are dropped first; when a single turn overflows on its
    own, that turn is clipped head-and-tail (never headless) and marked, so the
    model keeps both the instruction and the end of a long paste. When the
    window is unknown the fixed legacy caps apply.

    The kLLM path keeps ``strict_alternation=False``: consecutive same-role
    turns survive, which the relay accepts. The hosted Ollama path opts into
    strict alternation because some model chat templates are rendered from an
    alternating turn list.
    """
    max_messages, max_chars = context_fit_budget(context_window, requested_max_tokens)
    prepared: list[dict[str, str]] = []
    total_chars = 0

    for msg in reversed(messages):
        if len(prepared) >= max_messages:
            break
        role = getattr(msg, "role", None) if not isinstance(msg, dict) else msg.get("role")
        content_raw = (
            getattr(msg, "content", None) if not isinstance(msg, dict) else msg.get("content")
        )
        if role not in {"user", "assistant"}:
            continue
        content = sanitize_input(str(content_raw or "").strip())
        if not content:
            continue
        if prepared and total_chars + len(content) > max_chars:
            break
        if len(content) > max_chars:
            content = clip_to_budget(content, max_chars)
        prepared.append({"role": role, "content": content})
        total_chars += len(content)
        if total_chars >= max_chars:
            break

    prepared.reverse()
    while prepared and prepared[0]["role"] != "user":
        prepared.pop(0)
    if strict_alternation:
        prepared = _enforce_alternation(prepared, max_chars)
    return prepared


def _enforce_alternation(
    context: list[dict[str, str]], max_chars: int = MAX_CONTEXT_CHARS
) -> list[dict[str, str]]:
    """Collapse consecutive same-role turns into one, keeping strict alternation.

    The newest content is preserved by merging rather than dropping, so no user
    input is silently lost. The result starts and ends with a ``user`` turn and
    stays inside ``max_chars``.
    """
    merged: list[dict[str, str]] = []
    for message in context:
        if merged and merged[-1]["role"] == message["role"]:
            merged[-1] = {
                "role": message["role"],
                "content": f"{merged[-1]['content']}\n\n{message['content']}",
            }
        else:
            merged.append(dict(message))

    total_chars = sum(len(m["content"]) for m in merged)
    while len(merged) > 1 and total_chars > max_chars:
        removed = merged.pop(0)
        total_chars -= len(removed["content"])
    while merged and merged[0]["role"] != "user":
        total_chars -= len(merged.pop(0)["content"])
    while merged and merged[-1]["role"] != "user":
        total_chars -= len(merged.pop()["content"])
    if merged and total_chars > max_chars:
        merged[-1] = {
            "role": merged[-1]["role"],
            "content": clip_to_budget(merged[-1]["content"], max_chars),
        }
    return merged


def hosted_output_reserve(requested: int | None, context_window: int | None) -> int:
    """Output budget to reserve before fitting a hosted prompt to the window.

    Fitting the prompt first and only then deriving the generation budget would
    re-expand the budget into space the prompt already occupies, so the reserve is
    fixed up front from the request or a window-proportional default.
    """
    if requested is not None:
        # Never let an override take the whole window away from the prompt.
        return max(1, min(int(requested), max_output_tokens_for_window(context_window)))
    if not context_window or context_window <= 0:
        return DEFAULT_OUTPUT_TOKENS
    return min(MAX_OUTPUT_TOKENS, max(MIN_OUTPUT_TOKENS, context_window // 4))


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
    stream_factory: Callable[[], AsyncIterator[Any]] | None = None,
) -> AsyncIterator[str]:
    start = monotonic()
    last_event = start
    emitted = False
    finish_reason = "stop"
    # A clean EOF proves the connection ended, not that the model finished.
    # Only an upstream done/[DONE] frame is a terminal signal.
    terminal_seen = False
    ait = None
    try:
        if stream_factory is not None:
            stream = stream_factory()
        else:
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
                    # upstream finish_reason (e.g. "length") untouched, but it does
                    # prove the provider closed the stream on purpose.
                    terminal_seen = True
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
                    terminal_seen = True
                    reason = item.data.get("finish_reason")
                    if isinstance(reason, str) and reason:
                        finish_reason = reason
                continue

            delta = str(item)
            if not delta:
                continue
            emitted = True
            yield sse_event({"type": "delta", "content": delta})

        if not terminal_seen:
            # The upstream iterator ended without a terminal event. Report an
            # incomplete answer instead of claiming a clean "stop"; the client
            # surfaces it as an interrupted response.
            finish_reason = INCOMPLETE_FINISH_REASON
            logger.warning(
                "chat_stream_missing_terminal model=%s messages=%s emitted=%s duration_ms=%s",
                model,
                len(messages),
                emitted,
                int((monotonic() - start) * 1000),
            )
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
        # The lease is owned by the HTTP response (see LeaseStreamingResponse)
        # and released after this generator is closed, so closing the upstream
        # iterator is the only cleanup left here.
        aclose = getattr(ait, "aclose", None)
        if callable(aclose):
            try:
                await aclose()
            except Exception:
                pass
