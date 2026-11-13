from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


def test_livez():
    client = TestClient(app)
    r = client.get("/livez")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readyz_success():
    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, *a, **k):
            return None

    with patch("app.main.AsyncSessionLocal", return_value=FakeSession()):
        client = TestClient(app)
        r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["database"] == "connected"


def test_readyz_failure():
    class FakeSession:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, *a):
            return False

    with patch("app.main.AsyncSessionLocal", return_value=FakeSession()):
        client = TestClient(app)
        r = client.get("/readyz")
    assert r.status_code == 503
    assert r.json()["database"] == "disconnected"
