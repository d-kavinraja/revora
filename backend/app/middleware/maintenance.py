"""Maintenance-mode enforcement (phase 5, §12.3).

Backend-side single source of truth: while `platform_settings['maintenance']`
has `enabled=true`, every user API route (including safe GET reads) answers
`503 {"code": "maintenance"}` before any cookie is minted, while healthchecks,
webhooks, the public platform surface and the whole admin namespace keep
flowing unconditionally. In-flight reviews/SSE streams are untouched (this
only gates *new* HTTP requests); queued jobs persist and resume when the
worker's claim gate reopens.

Placement: first `add_middleware` call in `app/main.py` (Starlette LIFO ⇒
innermost), so CORS headers are present on every 503 and
`OriginCheckMiddleware` still covers admin mutations (§12.3 C4 note).
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.services.platform_settings import platform_settings_service

#: Prefixes that always pass during maintenance (§12.3). Segment-aware
#: matching keeps lookalike routes (e.g. /api/v1/platform-analytics) gated.
EXEMPT_PREFIXES = (
    "/readyz",
    "/livez",
    "/api/v1/health",
    "/api/v1/platform",
    "/api/v1/webhooks",
    "/api/v1/admin",
)


def is_maintenance_exempt(path: str) -> bool:
    """True when `path` must keep flowing during maintenance (§12.3)."""
    return any(
        path == prefix or path.startswith(prefix + "/")
        for prefix in EXEMPT_PREFIXES
    )


class MaintenanceMiddleware(BaseHTTPMiddleware):
    """503 every non-exempt API request while maintenance mode is enabled."""

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        if is_maintenance_exempt(path):
            return await call_next(request)
        if await platform_settings_service.is_enabled():
            return JSONResponse(status_code=503, content={"code": "maintenance"})
        return await call_next(request)
