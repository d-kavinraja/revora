"""Tests for the size-limit and origin-check middleware gates."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient

from app.middleware.size_limit import OriginCheckMiddleware, RequestSizeLimitMiddleware


def build_app() -> FastAPI:
    app = FastAPI()
    app.state.cors_origins = ["frontend.example.com"]
    app.add_middleware(
        RequestSizeLimitMiddleware, max_upload_size=10 * 1024 * 1024
    )
    app.add_middleware(OriginCheckMiddleware)

    @app.post("/api/v1/mouthmap/inference")
    async def inference(request: Request):
        return JSONResponse({"ok": True})

    @app.post("/api/v1/webhooks/github")
    async def webhook(request: Request):
        return JSONResponse({"ok": True})

    @app.post("/api/v1/auth/login")
    async def login(request: Request):
        return JSONResponse({"ok": True})

    return app


client = TestClient(build_app())


def test_mouthmap_missing_content_length_is_411():
    """A request without Content-Length must not reach the buffering handler."""
    resp = client.post(
        "/api/v1/mouthmap/inference",
        content=b"x",
        headers={"content-type": "multipart/form-data; boundary=x"},
        # httpx sends chunked transfer when content given as iterator; use
        # explicit header deletion to simulate a length-less upload.
    )
    # httpx always sets content-length for bytes; assert the middleware logic
    # directly for the length-less branch:
    from starlette.requests import Request as StarletteRequest

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/mouthmap/inference",
        "headers": [(b"content-type", b"multipart/form-data")],
        "query_string": b"",
    }
    mw = RequestSizeLimitMiddleware(app=build_app())
    req = StarletteRequest(scope)

    import asyncio

    async def run():
        return await mw.dispatch(req, lambda r: asyncio.sleep(0, JSONResponse({"ok": True})))

    out = asyncio.run(run())
    assert out.status_code == 411


def test_mouthmap_oversize_header_is_413():
    resp = client.post(
        "/api/v1/mouthmap/inference",
        content=b"x",
        headers={
            "content-type": "application/octet-stream",
            "content-length": str(60 * 1024 * 1024),  # lie is fine: gate is header-based
        },
    )
    assert resp.status_code == 413


def test_cross_origin_unsafe_request_is_403():
    resp = client.post(
        "/api/v1/auth/login",
        content=b"{}",
        headers={
            "content-type": "application/json",
            "origin": "https://evil.example.org",
        },
    )
    assert resp.status_code == 403


def test_allowlisted_origin_passes():
    resp = client.post(
        "/api/v1/auth/login",
        content=b"{}",
        headers={
            "content-type": "application/json",
            "origin": "https://frontend.example.com",
        },
    )
    assert resp.status_code == 200


def test_same_origin_host_passes():
    resp = client.post(
        "/api/v1/auth/login",
        content=b"{}",
        headers={
            "content-type": "application/json",
            "origin": "https://testserver",
        },
    )
    assert resp.status_code == 200


def test_webhook_origin_exempt():
    """GitHub's foreign Origin must not block HMAC-authenticated webhooks."""
    resp = client.post(
        "/api/v1/webhooks/github",
        content=b"{}",
        headers={
            "content-type": "application/json",
            "origin": "https://github.com",
        },
    )
    assert resp.status_code == 200
