"""Regression tests for owner-scoped chat leases and response-bound cleanup.

These tests pin the concurrency contract: one user may hold several chats at
once (bounded), a single chat may run only one generation, a lease can only be
released by its owner, and the lease is always released with the HTTP response
even when the client disconnects, validation fails, or cleanup is cancelled.
"""

from __future__ import annotations

import asyncio
import types
import uuid

import anyio
import pytest
from fastapi import HTTPException
from starlette.requests import ClientDisconnect

from app.api.v1.endpoints import chat as chat_endpoint
from app.api.v1.endpoints.chat_stream_response import LeaseStreamingResponse
from app.core import config as config_module
from app.services import chat_service
from app.services.chat_service import (
    ChatLease,
    acquire_chat_lease,
    reap_expired_chat_leases,
    release_chat_lease,
    reset_chat_runtime_state,
)


@pytest.fixture(autouse=True)
def _reset_runtime_state():
    reset_chat_runtime_state()
    yield
    reset_chat_runtime_state()


class _Clock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch) -> _Clock:
    fake = _Clock()
    monkeypatch.setattr(chat_service, "monotonic", fake)
    return fake


async def _admitted(user_id: str, chat_id: str | None) -> ChatLease:
    return await acquire_chat_lease(user_id, chat_id)


async def _assert_rejected(user_id: str, chat_id: str | None) -> None:
    with pytest.raises(HTTPException) as excinfo:
        await acquire_chat_lease(user_id, chat_id)
    assert excinfo.value.status_code == 429
    # The client-facing message must stay the generic one: a caller must never
    # learn whether the refusal came from its own chat or another one.
    assert isinstance(excinfo.value.detail, str)
    assert "already being generated" in excinfo.value.detail


# ---------------------------------------------------------------------------
# Lease registry
# ---------------------------------------------------------------------------


async def test_owner_release_frees_the_same_chat():
    lease = await _admitted("user-1", "chat-a")
    assert await release_chat_lease(lease) is True
    again = await _admitted("user-1", "chat-a")
    assert again.chat_id == "chat-a"


async def test_late_release_never_clears_a_newer_lease():
    first = await _admitted("user-1", "chat-a")
    assert await release_chat_lease(first) is True
    second = await _admitted("user-1", "chat-a")
    # A duplicate/late callback from the finished response must be a no-op.
    assert await release_chat_lease(first) is False
    await _assert_rejected("user-1", "chat-a")
    assert await release_chat_lease(second) is True
    await _admitted("user-1", "chat-a")


async def test_release_from_another_user_is_rejected():
    lease = await _admitted("user-1", "chat-a")
    forged = ChatLease(
        lease_id=lease.lease_id,
        user_id="user-2",
        chat_id=lease.chat_id,
        expires_at=lease.expires_at,
    )
    assert await release_chat_lease(forged) is False
    await _assert_rejected("user-1", "chat-a")


async def test_unknown_lease_release_is_a_noop():
    lease = ChatLease(
        lease_id="missing", user_id="user-1", chat_id="chat-a", expires_at=1.0
    )
    assert await release_chat_lease(lease) is False


async def test_duplicate_same_chat_request_is_rejected():
    lease = await _admitted("user-1", "chat-a")
    await _assert_rejected("user-1", "chat-a")
    await release_chat_lease(lease)


async def test_different_chats_of_one_user_run_concurrently():
    first = await _admitted("user-1", "chat-a")
    second = await _admitted("user-1", "chat-b")
    # Cap is two by default, so both are live at the same time.
    await _assert_rejected("user-1", "chat-c")
    assert await release_chat_lease(first) is True
    third = await _admitted("user-1", "chat-c")
    assert await release_chat_lease(second) is True
    assert await release_chat_lease(third) is True


async def test_per_user_cap_is_configurable(monkeypatch):
    monkeypatch.setattr(
        config_module.settings, "CHAT_MAX_CONCURRENT_REQUESTS_PER_USER", 1
    )
    lease = await _admitted("user-1", "chat-a")
    await _assert_rejected("user-1", "chat-b")
    await release_chat_lease(lease)


async def test_users_are_isolated_from_each_other():
    first = await _admitted("user-1", "same-chat")
    second = await _admitted("user-2", "same-chat")
    assert first.lease_id != second.lease_id
    assert await release_chat_lease(first) is True
    # Releasing user-1's lease must not free user-2's.
    await _assert_rejected("user-2", "same-chat")
    await release_chat_lease(second)


async def test_requests_without_chat_id_stay_backward_compatible():
    first = await _admitted("user-1", None)
    second = await _admitted("user-1", None)
    await _assert_rejected("user-1", None)
    assert await release_chat_lease(first) is True
    assert await release_chat_lease(second) is True
    # An anonymous-chat lease never blocks a named chat of the same user.
    named = await _admitted("user-1", "chat-a")
    await release_chat_lease(named)


async def test_release_after_expiry_still_frees_the_lease():
    lease = await _admitted("user-1", "chat-a")
    assert await release_chat_lease(lease) is True


async def test_reap_removes_only_expired_leases(clock):
    ttl = config_module.settings.CHAT_LEASE_TTL_SECONDS
    expired = await _admitted("user-1", "chat-old")
    clock.now = expired.expires_at + 1
    assert await reap_expired_chat_leases() == 1
    fresh = await _admitted("user-1", "chat-new")
    assert fresh.expires_at > clock.now
    # A new generation in the expired chat is admitted; the fresh one is not.
    reopened = await _admitted("user-1", "chat-old")
    await _assert_rejected("user-1", "chat-new")
    assert ttl > 0
    await release_chat_lease(reopened)
    await release_chat_lease(fresh)


async def test_expired_lease_is_reaped_on_the_next_acquire(clock):
    stale = await _admitted("user-1", "chat-a")
    clock.now = stale.expires_at + 1
    assert await reap_expired_chat_leases(clock.now) == 1
    replacement = await _admitted("user-1", "chat-a")
    assert replacement.lease_id != stale.lease_id
    await release_chat_lease(replacement)


async def test_stale_lease_release_does_not_clear_the_replacement(clock):
    stale = await _admitted("user-1", "chat-a")
    clock.now = stale.expires_at + 1
    replacement = await _admitted("user-1", "chat-a")
    assert await release_chat_lease(stale) is False
    await _assert_rejected("user-1", "chat-a")
    await release_chat_lease(replacement)


async def test_reset_clears_every_lease():
    lease = await _admitted("user-1", "chat-a")
    reset_chat_runtime_state()
    await _admitted("user-1", "chat-a")
    assert await release_chat_lease(lease) is False


# ---------------------------------------------------------------------------
# Response-bound cleanup
# ---------------------------------------------------------------------------


def _scope(spec_version: str = "2.4") -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": spec_version},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/v1/chat/completions",
        "raw_path": b"/api/v1/chat/completions",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }


async def _never_disconnect() -> dict:
    await asyncio.Event().wait()
    return {"type": "http.disconnect"}


async def _drive(response, *, send=None, receive=None, scope=None) -> list[dict]:
    sent: list[dict] = []

    async def _send(message: dict) -> None:
        sent.append(message)
        if send is not None:
            await send(message)

    await response(
        scope or _scope(),
        receive or _never_disconnect,
        _send,
    )
    return sent


async def test_lease_is_released_when_the_response_completes():
    released: list[bool] = []

    async def on_close() -> None:
        released.append(True)

    async def body():
        yield "hello"

    response = LeaseStreamingResponse(body(), on_close=on_close, media_type="text/plain")
    sent = await _drive(response)
    assert [m["type"] for m in sent] == [
        "http.response.start",
        "http.response.body",
        "http.response.body",
    ]
    assert released == [True]


async def test_lease_is_released_when_the_connection_fails_before_the_body():
    released: list[bool] = []
    started: list[bool] = []

    async def on_close() -> None:
        released.append(True)

    async def body():
        started.append(True)
        yield "hello"

    response = LeaseStreamingResponse(body(), on_close=on_close, media_type="text/plain")

    async def failing_send(message: dict) -> None:
        raise OSError("client went away")

    with pytest.raises(ClientDisconnect):
        await response(_scope(), _never_disconnect, failing_send)
    assert released == [True]
    # The generator was never iterated, so no provider work was started.
    assert started == []


async def test_response_closes_the_body_iterator_on_failure():
    released: list[bool] = []
    closed: list[bool] = []

    async def on_close() -> None:
        released.append(True)

    async def body():
        try:
            yield "first"
            yield "second"
        finally:
            closed.append(True)

    response = LeaseStreamingResponse(body(), on_close=on_close, media_type="text/plain")

    async def send(message: dict) -> None:
        if message["type"] == "http.response.body" and message.get("more_body"):
            raise OSError("broken pipe")

    with pytest.raises(ClientDisconnect):
        await response(_scope(), _never_disconnect, send)
    assert closed == [True]
    assert released == [True]


async def test_release_survives_a_failing_close():
    released: list[bool] = []

    async def on_close() -> None:
        released.append(True)

    async def body():
        yield "first"
        yield "second"

    response = LeaseStreamingResponse(body(), on_close=on_close, media_type="text/plain")

    async def send(message: dict) -> None:
        if message["type"] == "http.response.body" and message.get("more_body"):
            raise OSError("broken pipe")

    # aclose() of a suspended generator is normal, but the release must run even
    # if closing raises.
    class _ExplodingIterator:
        def __aiter__(self):
            return self

        async def __anext__(self):
            return "chunk"

        async def aclose(self):
            raise RuntimeError("close failed")

    response.body_iterator = _ExplodingIterator()
    with pytest.raises(ClientDisconnect):
        await response(_scope(), _never_disconnect, send)
    assert released == [True]


async def test_release_is_cancellation_safe_on_disconnect():
    released: list[bool] = []
    closed: list[bool] = []

    async def slow_release() -> None:
        await asyncio.sleep(0.05)
        released.append(True)

    async def body():
        try:
            yield "first"
            await asyncio.Event().wait()
        finally:
            closed.append(True)

    async def receive() -> dict:
        await asyncio.Event().wait()
        return {"type": "http.disconnect"}

    response = LeaseStreamingResponse(
        body(), on_close=slow_release, media_type="text/plain"
    )

    async def send(message: dict) -> None:
        return None

    # Cancelling an anyio cancel scope is how Starlette delivers a client
    # disconnect; the shielded cleanup must still finish.
    async def run() -> None:
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(
                lambda: response(_scope("2.4"), receive, send)
            )
            await asyncio.sleep(0.01)
            task_group.cancel_scope.cancel()

    await run()
    assert closed == [True]
    assert released == [True]


async def test_release_runs_exactly_once():
    count = 0

    async def on_close() -> None:
        nonlocal count
        count += 1

    async def body():
        yield "ok"

    response = LeaseStreamingResponse(body(), on_close=on_close, media_type="text/plain")
    await _drive(response)
    # A second call (an ASGI server retry, or a defensive close) must not
    # release a lease that already went back to the pool.
    await _drive(response)
    assert count == 1


# ---------------------------------------------------------------------------
# Endpoint integration: concurrency cap, chat single-flight, cleanup
# ---------------------------------------------------------------------------

MODEL = "qwen3.8-27b"


async def _quick_stream(*args, **kwargs):
    yield "data: {}\n\n"


@pytest.fixture
def endpoint(monkeypatch):
    user = types.SimpleNamespace(id=uuid.uuid4(), role="user")
    other = types.SimpleNamespace(id=uuid.uuid4(), role="user")
    calls: list[dict] = []

    async def fake_validate(request, current_user):
        return (
            MODEL,
            "kllm",
            [{"role": "user", "content": "hello"}],
            64,
            None,
            131_072,
        )

    async def fake_stream(*args, **kwargs):
        calls.append(kwargs)
        yield "data: {}\n\n"

    monkeypatch.setattr(chat_endpoint, "_validate_request", fake_validate)
    monkeypatch.setattr(chat_endpoint, "stream_chat_sse", fake_stream)
    return types.SimpleNamespace(user=user, other=other, calls=calls)


def _request(chat_id: str | None, *, stream: bool = True) -> chat_endpoint.ChatCompletionRequest:
    return chat_endpoint.ChatCompletionRequest(
        model=MODEL,
        messages=[{"role": "user", "content": "hello"}],
        stream=stream,
        chat_id=chat_id,
    )


async def _call_endpoint(request, user):
    return await chat_endpoint.create_chat_completion(
        request,
        http_request=types.SimpleNamespace(),
        current_user=user,
    )


async def _consume(response) -> None:
    await _drive(response, scope=_scope())


async def test_endpoint_admits_two_chats_of_one_user(endpoint):
    first = await _call_endpoint(_request("chat-a"), endpoint.user)
    second = await _call_endpoint(_request("chat-b"), endpoint.user)
    with pytest.raises(HTTPException) as excinfo:
        await _call_endpoint(_request("chat-c"), endpoint.user)
    assert excinfo.value.status_code == 429
    await _consume(first)
    await _consume(second)


async def test_endpoint_rejects_duplicate_chat(endpoint):
    first = await _call_endpoint(_request("chat-a"), endpoint.user)
    with pytest.raises(HTTPException) as excinfo:
        await _call_endpoint(_request("chat-a"), endpoint.user)
    assert excinfo.value.status_code == 429
    await _consume(first)


async def test_endpoint_isolates_users(endpoint):
    first = await _call_endpoint(_request("chat-a"), endpoint.user)
    second = await _call_endpoint(_request("chat-a"), endpoint.other)
    await _consume(first)
    await _consume(second)


async def test_endpoint_releases_the_lease_when_the_response_ends(endpoint):
    response = await _call_endpoint(_request("chat-a"), endpoint.user)
    await _consume(response)
    # The same chat is immediately usable again.
    again = await _call_endpoint(_request("chat-a"), endpoint.user)
    await _consume(again)


async def test_endpoint_releases_the_lease_when_validation_fails(endpoint, monkeypatch):
    async def failing_validate(request, current_user):
        raise HTTPException(status_code=400, detail="bad request")

    monkeypatch.setattr(chat_endpoint, "_validate_request", failing_validate)
    with pytest.raises(HTTPException):
        await _call_endpoint(_request("chat-a"), endpoint.user)
    # A failed attempt must not lock the chat for the lease TTL.
    monkeypatch.setattr(chat_endpoint, "_validate_request", endpoint_validate)
    response = await _call_endpoint(_request("chat-a"), endpoint.user)
    await _consume(response)


async def endpoint_validate(request, current_user):
    return (
        MODEL,
        "kllm",
        [{"role": "user", "content": "hello"}],
        64,
        None,
        131_072,
    )


async def test_endpoint_releases_the_lease_on_non_streaming_path(endpoint, monkeypatch):
    async def fake_complete(*args, **kwargs):
        return ("hi", 1, 1, "stop")

    monkeypatch.setattr("app.ai.llm.llm_service.complete_managed", fake_complete)
    first = await _call_endpoint(_request("chat-a", stream=False), endpoint.user)
    assert isinstance(first, chat_endpoint.JSONResponse)
    # Sequential non-streaming requests in the same chat must both be admitted.
    second = await _call_endpoint(_request("chat-a", stream=False), endpoint.user)
    assert isinstance(second, chat_endpoint.JSONResponse)


async def test_endpoint_releases_the_lease_when_cancelled(endpoint, monkeypatch):
    async def blocking_stream(*args, **kwargs):
        yield "data: {}\n\n"
        await asyncio.Event().wait()

    monkeypatch.setattr(chat_endpoint, "stream_chat_sse", blocking_stream)
    response = await _call_endpoint(_request("chat-a"), endpoint.user)
    task = asyncio.create_task(_consume(response))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    monkeypatch.setattr(chat_endpoint, "stream_chat_sse", _quick_stream)
    again = await _call_endpoint(_request("chat-a"), endpoint.user)
    await _consume(again)
