import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.middleware.correlation import CorrelationIdMiddleware, get_correlation_id

client = TestClient(app)


def test_correlation_id_middleware_generates_id():
    response = client.get("/livez")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) > 0


def test_correlation_id_middleware_preserves_custom_id():
    custom_id = "test-correlation-id-12345"
    response = client.get("/livez", headers={"X-Request-ID": custom_id})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == custom_id


def test_correlation_id_middleware_alt_header():
    custom_id = "alt-correlation-id-67890"
    response = client.get("/livez", headers={"X-Correlation-ID": custom_id})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == custom_id


def test_livez_and_health_endpoints():
    live_resp = client.get("/livez")
    assert live_resp.status_code == 200
    assert live_resp.json() == {"status": "ok"}

    health_resp = client.get("/api/v1/health")
    assert health_resp.status_code == 200
    assert health_resp.json()["status"] == "healthy"
