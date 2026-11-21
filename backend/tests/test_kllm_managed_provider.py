"""Safe, fully mocked tests for the managed local kLLM provider.

Nothing here contacts a real kLLM server, loads/stops/rotates a model, or
touches Kaggle. The service is exercised through ``_build_snapshot`` and
monkeypatched fetchers; the API is exercised through ``TestClient`` with the
in-memory test database.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.core import config as config_module
from app.core.deps import get_current_user
from app.main import app
from app.models.audit import AuditLog
from app.models.user import User
from app.services import kllm_service as ks


def _raw_state(*, healthy=True, left_s=10000):
    return ks._RawState(
        fetched_at=time.monotonic(),
        reachable=True,
        error=None,
        models={
            "data": [
                {
                    "id": "qwen3.8-27b",
                    "status": {"value": "loaded"},
                    "architecture": {"input_modalities": ["text"]},
                    "tags": [],
                    "context_length": 131072,
                }
            ]
        },
        backends={
            "backends": [
                {
                    "account": "kaggle-secret-account",
                    "user": "person@example.com",
                    "url": "https://tunnel-secret.example",
                    "host": "10.0.0.9",
                    "api_key": "gateway-secret-key",
                    "model_key": "qwen3.8-27b",
                    "healthy": healthy,
                    "left_s": left_s,
                    "draining": False,
                    "replaced_by": None,
                    "sessions": 2,
                    "inflight": 1,
                    "idle_s": 5,
                    "errors_5m": 0,
                    "pinned": False,
                    "res": {"gpu": [{"index": 0}], "gpu_used_mib": 1024},
                }
            ],
            "supervisor": True,
            "clients": [{"kind": "API", "sessions": 2, "rpm": 3}],
            "traffic": {"rpm": 3, "ttft_p50": 0.4},
        },
        health={"ok": True, "inflight": 1},
    )


def test_snapshot_never_leaks_account_identity_or_secrets():
    snap = ks._build_snapshot(
        _raw_state(), enabled=True, configured=True, disabled_models=set()
    )
    payload = snap.as_dict()
    blob = json.dumps(payload)

    for secret in (
        "kaggle-secret-account",
        "person@example.com",
        "tunnel-secret.example",
        "10.0.0.9",
        "gateway-secret-key",
    ):
        assert secret not in blob

    backend = payload["backends"][0]
    # Opaque UUID, never the account name.
    uuid.UUID(backend["id"])
    assert backend["id"] != "kaggle-secret-account"
    assert backend["state"] == "running"
    # The only URL-ish field is the sanitized GPU summary, never the tunnel.
    assert "url" not in backend
    assert "account" not in backend
    assert "user" not in backend

    # Loaded + one fresh healthy backend => ready.
    model = payload["models"][0]
    assert model["loaded"] is True
    assert model["ready"] is True
    assert model["backend_count"] == 1


def test_readiness_requires_explicit_health_and_freshness():
    base = {"host": "10.0.0.9", "left_s": 10000}
    # Missing `healthy` must not be treated as healthy.
    assert ks._backend_ready(dict(base), fresh=True) is False
    # Explicit healthy + fresh + not draining.
    assert ks._backend_ready({**base, "healthy": True}, fresh=True) is True
    # Stale snapshots are never ready.
    assert ks._backend_ready({**base, "healthy": True}, fresh=False) is False
    # Explicit draining / retiring.
    assert (
        ks._backend_ready(
            {**base, "healthy": True, "draining": True}, fresh=True
        )
        is False
    )
    assert (
        ks._backend_ready(
            {**base, "healthy": True, "replaced_by": "other"}, fresh=True
        )
        is False
    )
    # left_s inside the prelaunch lead window implies draining.
    assert (
        ks._backend_ready({**base, "healthy": True, "left_s": 100}, fresh=True)
        is False
    )
    # No host/URL => not ready.
    assert ks._backend_ready({"healthy": True}, fresh=True) is False


def test_status_is_gated_when_disabled(client, monkeypatch):
    async def _false(db):
        return False

    monkeypatch.setattr(config_module.settings, "KLLM_ENABLED", False, raising=False)
    monkeypatch.setattr(ks, "is_enabled", _false)
    monkeypatch.setattr(ks, "is_configured", _false)

    response = client.get("/api/v1/kllm/status")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["reachable"] is False
    assert body["models"] == []
    assert body["backends"] == []
    # Ordinary users never receive a lifecycle-control capability flag.
    assert "can_manage" not in body

    # Model selection and telemetry are hard-gated.
    assert client.get("/api/v1/kllm/models").status_code == 503
    assert client.get("/api/v1/kllm/telemetry").status_code == 503

    # The "kLLM is off" details are user-facing: they must never leak the
    # backend/.env path, the env var name or restart steps.
    for path in ("/api/v1/kllm/models", "/api/v1/kllm/telemetry"):
        detail = client.get(path).json().get("detail", "")
        assert "KLLM_ENABLED" not in detail
        assert "backend/.env" not in detail
        assert "restart" not in detail


def test_disabled_message_is_user_facing_clean():
    """The kLLM-off 503 copy carries no developer-facing instructions."""
    assert ks.DISABLED_MESSAGE
    assert "KLLM_ENABLED" not in ks.DISABLED_MESSAGE
    assert ".env" not in ks.DISABLED_MESSAGE
    assert "restart" not in ks.DISABLED_MESSAGE


def test_activity_is_gated_when_disabled(client, monkeypatch):
    monkeypatch.setattr(config_module.settings, "KLLM_ENABLED", False, raising=False)
    response = client.get("/api/v1/kllm/activity")
    assert response.status_code == 200
    assert response.json() == {"enabled": False, "items": []}


def test_user_namespace_has_no_lifecycle_routes(client):
    """Lifecycle mutations live only in the isolated admin namespace.

    The old `/api/v1/kllm/admin/*` surface is removed: the user namespace
    fails closed with 404 instead of doing an in-handler role check.
    """
    assert client.post("/api/v1/kllm/admin/refresh").status_code == 404
    assert (
        client.post(
            "/api/v1/kllm/admin/models/load",
            json={"model": "qwen3.8-27b", "confirm": True},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/kllm/admin/models/unload",
            json={"model": "qwen3.8-27b", "confirm": True},
        ).status_code
        == 404
    )
    assert client.post("/api/v1/kllm/admin/keep", json={"size": 0}).status_code == 404
    assert (
        client.post(
            f"/api/v1/kllm/admin/backends/{uuid.uuid4()}/stop",
            json={"confirm": True},
        ).status_code
        == 404
    )


async def _make_admin(test_db) -> User:
    user = User(
        id=uuid.uuid4(),
        name="Admin User",
        email="admin@example.com",
        role="admin",
        is_verified=True,
    )
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


async def test_admin_load_requires_confirmation_and_is_audited(
    admin_client, test_db, monkeypatch
):
    monkeypatch.setattr(config_module.settings, "KLLM_ENABLED", True, raising=False)

    async def fake_load(db, model, *, confirm=False):
        if not confirm:
            raise ks.KllmConflictError("Confirmation required.")
        return {"status": "loading", "model": model}

    monkeypatch.setattr(ks, "load_model", fake_load)

    denied = admin_client.post(
        "/api/v1/admin/kllm/models/load",
        json={"model": "qwen3.8-27b", "confirm": False},
    )
    assert denied.status_code == 409

    ok = admin_client.post(
        "/api/v1/admin/kllm/models/load",
        json={"model": "qwen3.8-27b", "confirm": True},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "loading"

    rows = (
        (
            await test_db.execute(
                select(AuditLog).where(AuditLog.action == "admin.kllm_model_load")
            )
        )
        .scalars()
        .all()
    )
    assert rows
    assert all("gateway-secret" not in json.dumps(r.details) for r in rows)


def test_ready_models_endpoint_only_returns_ready(client, monkeypatch):
    monkeypatch.setattr(config_module.settings, "KLLM_ENABLED", True, raising=False)

    async def fake_ready(db):
        return [
            ks.KllmModel(
                key="qwen3.8-27b",
                status="loaded",
                loaded=True,
                ready=True,
                context_window=131072,
                vision=False,
                tags=[],
                backend_count=1,
            )
        ]

    monkeypatch.setattr(ks, "get_ready_models", fake_ready)
    response = client.get("/api/v1/kllm/models")
    assert response.status_code == 200
    assert [row["key"] for row in response.json()] == ["qwen3.8-27b"]


async def test_build_available_models_returns_only_ready(monkeypatch):
    ready = ks.KllmModel(
        key="qwen3.8-27b",
        status="loaded",
        loaded=True,
        ready=True,
        context_window=131072,
        vision=False,
        tags=[],
        backend_count=1,
    )
    loading = ks.KllmModel(
        key="nanbeige4.3-33b-128k",
        status="loading",
        loaded=False,
        ready=False,
        context_window=131072,
        vision=False,
        tags=[],
        backend_count=0,
    )
    snapshot = ks.KllmSnapshot(
        enabled=True,
        configured=True,
        reachable=True,
        stale=False,
        generated_at=datetime.now(UTC),
        age_seconds=0.0,
        error=None,
        relay_health={"ok": True, "inflight": 0},
        models=[ready, loading],
        backends=[],
        pending=[],
        summary={},
        clients=[],
        traffic={},
        supervisor=False,
        autoscale=False,
    )

    async def fake_snapshot(db, *, force=False):
        return snapshot

    monkeypatch.setattr(ks, "get_snapshot", fake_snapshot)
    rows = await ks.build_available_models(None)
    assert [row["model_name"] for row in rows] == ["qwen3.8-27b"]
    assert rows[0]["provider"] == "kllm"


def test_no_per_model_unload_route_in_user_namespace(client):
    # kLLM's /chat-ui/models/unload is a no-op; Revora must not expose it in
    # the user namespace. The admin namespace exposes a composed unload.
    response = client.post(
        "/api/v1/kllm/admin/models/unload", json={"model": "qwen3.8-27b"}
    )
    assert response.status_code in (404, 405)


def test_non_loopback_relay_with_gateway_key_is_allowed(monkeypatch):
    """A server-side gateway key authorizes a non-loopback relay URL."""
    monkeypatch.setattr(
        config_module.settings,
        "KLLM_SERVER_URL",
        "http://172.18.0.1:18080",
        raising=False,
    )
    monkeypatch.setattr(
        config_module.settings,
        "KLLM_GATEWAY_API_KEY",
        "server-only-key",
        raising=False,
    )
    monkeypatch.setattr(ks, "_raw_cache", None, raising=False)
    fetched: list[str] = []

    async def fake_fetch(path, *, timeout):
        fetched.append(path)
        if path == "/chat-ui/v1/models":
            return {"data": []}, None
        if path == "/admin/api/backends":
            return {"backends": []}, None
        return {"ok": True}, None

    monkeypatch.setattr(ks, "_fetch_json", fake_fetch)
    state = asyncio.run(ks._read_raw_state(force=True))
    assert state.reachable is True
    assert state.error is None
    assert fetched == [
        "/chat-ui/v1/models",
        "/admin/api/backends",
        "/__relay/health",
    ]


def test_non_loopback_without_gateway_key_is_still_local_only(monkeypatch):
    monkeypatch.setattr(
        config_module.settings,
        "KLLM_SERVER_URL",
        "http://172.18.0.1:18080",
        raising=False,
    )
    monkeypatch.setattr(
        config_module.settings, "KLLM_GATEWAY_API_KEY", None, raising=False
    )
    monkeypatch.setattr(ks, "_raw_cache", None, raising=False)
    state = asyncio.run(ks._read_raw_state(force=True))
    assert state.reachable is False
    assert state.error and "local-only" in state.error
