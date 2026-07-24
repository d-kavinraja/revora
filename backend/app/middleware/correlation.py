import uuid
from contextvars import ContextVar
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

correlation_id_ctx: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> Optional[str]:
    """Retrieve the correlation ID for the current context."""
    return correlation_id_ctx.get()


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Middleware that injects an X-Request-ID correlation ID into all incoming requests.

    If X-Request-ID or X-Correlation-ID header is present in the request, it is used.
    Otherwise, a new UUID v4 is generated.
    The ID is attached to request.state.correlation_id, stored in a contextvar,
    and returned in the X-Request-ID response header.
    """

    HEADER_NAME = "X-Request-ID"
    ALT_HEADER_NAME = "X-Correlation-ID"

    async def dispatch(self, request: Request, call_next) -> Response:
        correlation_id = (
            request.headers.get(self.HEADER_NAME)
            or request.headers.get(self.ALT_HEADER_NAME)
            or str(uuid.uuid4())
        )

        request.state.correlation_id = correlation_id
        token = correlation_id_ctx.set(correlation_id)

        try:
            response = await call_next(request)
            response.headers[self.HEADER_NAME] = correlation_id
            return response
        finally:
            correlation_id_ctx.reset(token)
