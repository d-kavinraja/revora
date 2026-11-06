
from fastapi.testclient import TestClient

from app.main import app


def test_webhook_invalid_signature_returns_401():
    client = TestClient(app)
    body = b'{"action":"created"}'
    response = client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "installation",
            "X-GitHub-Delivery": "delivery-1",
            "X-Hub-Signature-256": "sha256=invalid",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 401
