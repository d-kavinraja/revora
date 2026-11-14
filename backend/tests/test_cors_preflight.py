"""CORS preflight regression tests.

A disallowed origin must not be able to bypass the preflight guard, while
every origin the frontend actually uses in development (including an
arbitrary localhost port) must pass preflight so the browser can call the
API.
"""

from fastapi.testclient import TestClient

from app.main import app


def test_preflight_allowed_localhost_port():
    client = TestClient(app)
    response = client.options(
        "/api/v1/platform/features",
        headers={
            "Origin": "http://localhost:3999",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3999"


def test_preflight_allowed_configured_origin():
    client = TestClient(app)
    response = client.options(
        "/api/v1/platform/features",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_preflight_disallowed_origin():
    client = TestClient(app)
    response = client.options(
        "/api/v1/platform/features",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 400
    assert response.headers.get("access-control-allow-origin") is None


def test_preflight_carries_credentials():
    client = TestClient(app)
    response = client.options(
        "/api/v1/platform/features",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-credentials") == "true"