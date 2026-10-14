from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from urllib.parse import urlparse


from app.core.config import settings


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_upload_size: int = 10 * 1024 * 1024):  # 10MB default
        super().__init__(app)
        self.max_upload_size = max_upload_size
        # MouthMap uploads are legitimately large. Enforce a separate,
        # explicit cap so general tightening never breaks /inference
        # and oversized videos are rejected before the handler buffers them.
        # The hard byte cap is max(upload setting, 55MB floor for the header
        # pre-check); the streaming endpoint enforces the exact setting.
        self.mouthmap_paths = ("/api/v1/mouthmap/inference", "/mouthmap/inference")

    @property
    def mouthmap_max_bytes(self) -> int:
        return max(int(settings.MOUTHMAP_MAX_UPLOAD_MB or 50), 55) * 1024 * 1024

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if "/webhooks/github" in path:
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > self.max_upload_size:
                return JSONResponse(
                    status_code=413, content={"detail": "Payload too large"}
                )
        if path in self.mouthmap_paths or path.endswith("/mouthmap/inference"):
            content_length = request.headers.get("content-length")
            if content_length is None:
                # Without a declared length the pre-buffer cap cannot be
                # enforced, so reject instead of buffering blindly (411).
                # All real browsers/XHR send Content-Length for uploads.
                return JSONResponse(
                    status_code=411,
                    content={"detail": "Content-Length is required for video uploads."},
                )
            try:
                declared = int(content_length)
            except (TypeError, ValueError):
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid Content-Length header."},
                )
            if declared > self.mouthmap_max_bytes:
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": f"Video is too large. Maximum size is {settings.MOUTHMAP_MAX_UPLOAD_MB} MB."
                    },
                )
        return await call_next(request)


class OriginCheckMiddleware(BaseHTTPMiddleware):
    """CSRF guard for cookie-authenticated unsafe requests.

    The session cookie is SameSite=Lax, which already blocks cross-site
    POSTs in modern browsers. This is the second layer: any unsafe method
    that carries an Origin header must come from the API itself or from a
    CORS-allowlisted origin. Bearer-header callers are unaffected (an
    attacker cannot attach the Authorization header cross-site).
    """

    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
    # Webhooks are authenticated by HMAC signature, not cookies — CSRF
    # cannot apply (an attacker cannot forge the signature), and GitHub's
    # Origin header is foreign by nature, so they must be exempt.
    EXEMPT_PREFIXES = ("/api/v1/webhooks/", "/webhooks/")

    async def dispatch(self, request: Request, call_next):
        if request.method in self.SAFE_METHODS:
            return await call_next(request)
        path = request.url.path
        if any(path.startswith(p) for p in self.EXEMPT_PREFIXES):
            return await call_next(request)

        origin = request.headers.get("origin")
        if origin:
            allowed = set(request.app.state.cors_origins or [])
            # Same-origin and non-browser clients (Origin absent) pass.
            self_host = request.headers.get("host", "")
            origin_netloc = urlparse(origin).netloc
            if origin_netloc not in allowed and origin_netloc != self_host:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Cross-origin request blocked."},
                )
        return await call_next(request)
