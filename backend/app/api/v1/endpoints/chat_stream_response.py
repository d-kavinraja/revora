"""SSE response whose own lifetime owns the chat lease."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterable, Awaitable, Callable, MutableMapping
from typing import Any

import anyio
from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]


class LeaseStreamingResponse(StreamingResponse):
    """Release a chat lease when the HTTP response is truly finished.

    Starlette can fail or be cancelled before it ever iterates the body (the
    client is already gone when the headers are sent), and a disconnect
    cancels the streaming task. Releasing from the generator's ``finally`` is
    therefore not enough: the lease is released from ``__call__``'s
    ``finally`` instead, after the body iterator is closed.

    Cleanup is shielded so an in-flight cancellation cannot skip it, and is
    idempotent so a retried call cannot release a newer lease by accident
    (``release_chat_lease`` is owner-scoped as well).
    """

    def __init__(
        self,
        content: AsyncIterable[str],
        *,
        on_close: Callable[[], Awaitable[None]],
        **kwargs: Any,
    ) -> None:
        super().__init__(content, **kwargs)
        self._on_close = on_close
        self._closed = False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self.aclose_and_release()

    async def aclose_and_release(self) -> None:
        """Close the body exactly once, then release the lease."""
        if self._closed:
            return
        self._closed = True
        with anyio.CancelScope(shield=True):
            aclose = getattr(self.body_iterator, "aclose", None)
            if callable(aclose):
                try:
                    await aclose()
                except BaseException:
                    # Close failures (including a secondary cancellation raised
                    # inside the generator's teardown) must never skip release.
                    logger.debug("chat_stream_aclose_failed", exc_info=True)
            try:
                await self._on_close()
            except BaseException:
                logger.warning("chat_stream_lease_release_failed", exc_info=True)