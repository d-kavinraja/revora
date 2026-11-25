"""Mocked tests for the explicit admin-only hosted model load endpoint.

No test performs a real model load, unload or inference.
"""

from __future__ import annotations

import uuid

import pytest

from app.core import config as config_module
from app.services import hosted_ollama_service as hosted

from app.middleware.rate_limit import limiter

MODEL = "qwen3:1.7b-q4_K_M"
KEY = hosted.hosted_key(MODEL)


@pytest.fixture(autouse=True)
def _reset_limiter():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_OLLAMA_ENABLED", True, raising=False)
    monkeypatch.setattr(config_module.settings, "REVORA_HOSTED_WAKE_ENABLED", False, raising=False)
    hosted.reset_runtime_state()
    yield
    hosted.reset_runtime_state()


async def test_load_requires_admin(anon_client):
    response = anon_client.post(
        "/api/v1/admin/hosted-ollama/models/load",
        json={"model": KEY, "confirm": True},
    )
    assert response.status_code in (401, 403)


async def test_load_requires_confirmation(admin_client):
    response = admin_client.post(
        "/api/v1/admin/hosted-ollama/models/load",
        json={"model": KEY, "confirm": False},
    )
    assert response.status_code == 409


async def test_load_unknown_model_returns_404(admin_client, monkeypatch):
    async def fake_load(db, model):
        raise hosted.HostedNotFoundError(
            "Model is not installed.", definitive=True, reason_code="model_not_found"
        )

    monkeypatch.setattr(hosted, "load_model", fake_load)
    response = admin_client.post(
        "/api/v1/admin/hosted-ollama/models/load",
        json={"model": KEY, "confirm": True},
    )
    assert response.status_code == 404


async def test_load_already_loaded(admin_client, monkeypatch):
    async def fake_load(db, model):
        return {"status": "already_loaded", "model": MODEL, "verified": True}

    monkeypatch.setattr(hosted, "load_model", fake_load)
    response = admin_client.post(
        "/api/v1/admin/hosted-ollama/models/load",
        json={"model": KEY, "confirm": True},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "already_loaded"
    assert body["verified"] is True


async def test_load_success(admin_client, monkeypatch):
    async def fake_load(db, model):
        return {"status": "loaded", "model": MODEL, "verified": True}

    monkeypatch.setattr(hosted, "load_model", fake_load)
    response = admin_client.post(
        "/api/v1/admin/hosted-ollama/models/load",
        json={"model": KEY, "confirm": True},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "loaded"
    assert body["verified"] is True
    assert "token" not in str(body).lower()
    assert "ibk_" not in str(body)


async def test_load_failure_returns_safe_error(admin_client, monkeypatch):
    async def fake_load(db, model):
        raise hosted.HostedUnavailableError(
            "Hosted Ollama is unreachable.", reason_code="hosted_unavailable"
        )

    monkeypatch.setattr(hosted, "load_model", fake_load)
    response = admin_client.post(
        "/api/v1/admin/hosted-ollama/models/load",
        json={"model": KEY, "confirm": True},
    )
    assert response.status_code == 503
    assert "ibk_" not in response.text


async def test_load_timeout(admin_client, monkeypatch):
    async def fake_load(db, model):
        return {"status": "timeout", "model": MODEL, "verified": False, "reason_code": "load_timeout"}

    monkeypatch.setattr(hosted, "load_model", fake_load)
    response = admin_client.post(
        "/api/v1/admin/hosted-ollama/models/load",
        json={"model": KEY, "confirm": True},
    )
    assert response.status_code == 200
    assert response.json()["verified"] is False
    assert response.json()["status"] == "timeout"


async def test_load_invalid_model_id_rejected(admin_client, monkeypatch):
    response = admin_client.post(
        "/api/v1/admin/hosted-ollama/models/load",
        json={"model": "hosted-ollama:../etc/passwd", "confirm": True},
    )
    assert response.status_code in (400, 404, 409, 422, 503)


async def test_load_conflict(admin_client, monkeypatch):
    async def fake_load(db, model):
        raise hosted.HostedConflictError("Another model load is already in progress.", reason_code="load_in_progress")

    monkeypatch.setattr(hosted, "load_model", fake_load)
    response = admin_client.post(
        "/api/v1/admin/hosted-ollama/models/load",
        json={"model": KEY, "confirm": True},
    )
    assert response.status_code == 409