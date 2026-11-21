"""Additional mocked coverage for session policies and admin precedence."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.core import config as config_module
from app.core.auth import create_access_token, decode_access_token
from app.middleware.rate_limit import limiter
from app.models.audit import AuditLog
from app.models.provider import ProviderRegistry
from app.models.review import Review
from app.queue import worker as worker_module
from app.services import kllm_autoload, kllm_service, user_presence
from app.services.kllm_service import KllmModel
from app.services.review_execution_service import create_execution, get_latest_execution

MODEL = "qwen3.8-27b"


@pytest.fixture
def gateway_enabled(monkeypatch):
    monkeypatch.setattr(config_module.settings, "KLLM_ENABLED", True, raising=False)
    return True


async def _seed_provider(db, *, default_model: str | None = MODEL) -> None:
    db.add(
        ProviderRegistry(
            name="kllm",
            display_name="kLLM",
            slug="kllm",
            litellm_provider="openai",
            default_model=default_model or MODEL,
            api_key_min_length=1,
            is_enabled=True,
            status="available",
            is_managed=True,
            allow_key_addition=False,
        )
    )
    await db.commit()


def _model(status: str) -> KllmModel:
    return KllmModel(
        key=MODEL,
        status=status,
        loaded=status == "loaded",
        ready=status == "loaded",
        context_window=131072,
        vision=False,
        tags=[],
        backend_count=1 if status == "loaded" else 0,
        readiness="ready" if status == "loaded" else status,
        reason_code="ready" if status == "loaded" else "model_unloaded",
    )


def _payload() -> dict[str, Any]:
    token = create_access_token(
        subject=str(uuid.uuid4()), expires_delta=timedelta(hours=1)
    )
    return decode_access_token(token)


async def _enabled(db):
    return True


# ---------------------------------------------------------------------------
# GitHub login and cooldown
# ---------------------------------------------------------------------------


async def test_github_login_schedules_one_shot_preload(
    anon_client, test_db, monkeypatch
):
    limiter.reset()
    monkeypatch.setattr(config_module.settings, "GITHUB_CLIENT_ID", "client", raising=False)
    monkeypatch.setattr(config_module.settings, "GITHUB_CLIENT_SECRET", "secret", raising=False)

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        @property
        def is_success(self):
            return True

        def json(self):
            return self._payload

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *args, **kwargs):
            return FakeResponse({"access_token": "gh-token"})

        async def get(self, url, *args, **kwargs):
            if url.endswith("/user"):
                return FakeResponse(
                    {
                        "id": 424242,
                        "login": "octocat",
                        "name": "Octo Cat",
                        "email": "octo@example.com",
                    }
                )
            raise AssertionError(f"unexpected GitHub request: {url}")

    monkeypatch.setattr(
        "app.api.v1.endpoints.auth.httpx.AsyncClient", FakeAsyncClient
    )
    scheduled: list[Any] = []

    async def no_reconciliation(user_id):
        return None

    monkeypatch.setattr(
        "app.api.v1.endpoints.auth._login_reconciliation", no_reconciliation
    )
    monkeypatch.setattr(
        "app.api.v1.endpoints.auth.schedule_login_preload",
        lambda background_tasks, user_id: scheduled.append(user_id),
    )

    response = anon_client.post(
        "/api/v1/auth/github",
        json={"code": "one-time-code", "redirect_uri": "http://localhost/callback"},
    )
    assert response.status_code == 200, response.text
    assert len(scheduled) == 1


async def test_login_preload_cooldown_suppresses_second_request(monkeypatch):
    requested: list[str] = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def get_bind(self):
            return type("Bind", (), {"dialect": type("Dialect", (), {"name": "sqlite"})})()

    async def fake_policy(db=None, *, force=True):
        return kllm_autoload._normalize_policy(
            {
                "login_preload": {
                    "enabled": True,
                    "allowed_models": [MODEL],
                },
                "login_preload_cooldown_seconds": 60,
            },
            1,
        )

    async def fake_read(db, model):
        return _model("unloaded")

    async def fake_request(db, model, policy):
        requested.append(model)
        return {"status": "loading", "model": model}

    async def fake_assert(db, model):
        return None

    monkeypatch.setattr(kllm_autoload, "AsyncSessionLocal", lambda: FakeSession())
    monkeypatch.setattr(kllm_autoload, "get_policy", fake_policy)
    monkeypatch.setattr(kllm_autoload, "_read_model", fake_read)
    monkeypatch.setattr(kllm_autoload, "_request_load_once", fake_request)
    monkeypatch.setattr(kllm_autoload, "_assert_load_allowed", fake_assert)
    monkeypatch.setattr(kllm_autoload, "_login_last_request", {})

    await kllm_autoload.preload_after_login(uuid.uuid4())
    await kllm_autoload.preload_after_login(uuid.uuid4())
    assert requested == [MODEL]


# ---------------------------------------------------------------------------
# concurrency and no unload
# ---------------------------------------------------------------------------


async def test_concurrent_heartbeats_issue_only_one_load(
    test_db, gateway_enabled, mock_user, monkeypatch
):
    await _seed_provider(test_db)
    await kllm_autoload.update_policy(
        test_db,
        {"active_session_autoload": {"enabled": True, "allowed_models": [MODEL]}},
    )
    await user_presence.upsert_heartbeat(
        test_db,
        user_id=mock_user.id,
        payload=_payload(),
        client_session_id=str(uuid.uuid4()),
        active=True,
    )
    await test_db.commit()
    state = {"loaded": False}

    async def fake_read(db, model):
        return _model("loaded" if state["loaded"] else "unloaded")

    monkeypatch.setattr(kllm_service, "is_enabled", _enabled)
    monkeypatch.setattr(kllm_autoload, "_read_model", fake_read)

    requested: list[str] = []

    async def fake_request(db, model, policy):
        requested.append(model)
        state["loaded"] = True
        return {"status": "loading", "model": model}

    monkeypatch.setattr(kllm_autoload, "_request_load_once", fake_request)
    await asyncio.gather(
        kllm_autoload.reconcile_session_models(test_db),
        kllm_autoload.reconcile_session_models(test_db),
    )
    assert requested == [MODEL]


async def test_ending_presence_never_calls_kllm_unload(
    test_db, gateway_enabled, mock_user, monkeypatch
):
    await _seed_provider(test_db)
    await kllm_autoload.update_policy(
        test_db,
        {"active_session_autoload": {"enabled": True, "allowed_models": [MODEL]}},
    )
    session_id = str(uuid.uuid4())
    await user_presence.upsert_heartbeat(
        test_db,
        user_id=mock_user.id,
        payload=_payload(),
        client_session_id=session_id,
        active=True,
    )
    await user_presence.deactivate(
        test_db, user_id=mock_user.id, client_session_id=session_id
    )
    await test_db.commit()

    async def forbidden_unload(*args, **kwargs):
        raise AssertionError("presence changes must never unload a kLLM model")

    monkeypatch.setattr(kllm_service, "unload_model", forbidden_unload)
    monkeypatch.setattr(kllm_service, "is_enabled", _enabled)
    results = await kllm_autoload.reconcile_session_models(test_db)
    assert results == []


# ---------------------------------------------------------------------------
# admin API projections and precedence
# ---------------------------------------------------------------------------


async def test_admin_status_exposes_presence_blocks_and_always_on(
    admin_client, test_db, mock_user, monkeypatch
):
    monkeypatch.setattr(config_module.settings, "KLLM_ENABLED", False, raising=False)

    async def fake_snapshot(db, *, force=False):
        return kllm_service.KllmSnapshot(
            enabled=False,
            configured=False,
            reachable=False,
            stale=False,
            generated_at=datetime.now(UTC),
            age_seconds=0,
            error=None,
            relay_health={"ok": False, "inflight": 0},
            models=[],
            backends=[],
            pending=[],
            summary={},
            clients=[],
            traffic={},
            supervisor=False,
            autoscale=False,
        )

    monkeypatch.setattr(kllm_service, "get_snapshot", fake_snapshot)
    await kllm_autoload.set_manual_block(test_db, MODEL, admin_id=uuid.uuid4())
    await user_presence.upsert_heartbeat(
        test_db,
        user_id=mock_user.id,
        payload=_payload(),
        client_session_id=str(uuid.uuid4()),
        active=True,
    )
    await test_db.commit()

    response = admin_client.get("/api/v1/admin/kllm")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["active_sessions"] == 1
    assert body["manual_unload_blocks"][0]["model"] == MODEL
    assert body["always_on_size"] is None
    assert body["always_on_verified"] is False
    assert body["autoload"]["active_session_autoload"]["enabled"] is False


async def test_admin_unload_returns_structured_always_on_conflict(
    admin_client, test_db, gateway_enabled, monkeypatch
):
    await _seed_provider(test_db)

    async def fake_default(db):
        return MODEL

    async def fake_config():
        return {
            "reachable": True,
            "size": 2,
            "enabled": True,
            "verified": True,
            "autoscale_min_backends": 2,
            "desired_pool": 0,
        }

    async def forbidden_unload(*args, **kwargs):
        raise AssertionError("conflicting unload must not reach kLLM")

    monkeypatch.setattr(kllm_service, "get_default_model", fake_default)
    monkeypatch.setattr(kllm_service, "get_autoscale_config", fake_config)
    monkeypatch.setattr(kllm_service, "unload_model", forbidden_unload)

    response = admin_client.post(
        "/api/v1/admin/kllm/models/unload",
        json={"model": MODEL, "confirm": True, "force": False},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "always_on_conflict"


async def test_admin_can_clear_manual_unload_block(
    admin_client, test_db, gateway_enabled
):
    await kllm_autoload.set_manual_block(test_db, MODEL, admin_id=uuid.uuid4())
    await test_db.commit()

    response = admin_client.post(
        "/api/v1/admin/kllm/models/allow-autoload",
        json={"model": MODEL, "confirm": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["manual_block_cleared"] is True
    assert await kllm_autoload.is_manually_blocked(test_db, MODEL) is False
    rows = (
        (
            await test_db.execute(
                select(AuditLog).where(
                    AuditLog.action == "admin.kllm_autoload_unblocked"
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows


async def test_worker_readiness_reports_manual_unload_block(
    test_db, gateway_enabled, monkeypatch
):
    await _seed_provider(test_db)
    review = Review(pr_id=uuid.uuid4(), status="running")
    test_db.add(review)
    await test_db.flush()
    await create_execution(
        test_db,
        review.id,
        trigger="webhook",
        provider="kllm",
        model=MODEL,
    )
    await kllm_autoload.set_manual_block(test_db, MODEL, admin_id=uuid.uuid4())
    await test_db.commit()

    async def fake_snapshot(db, *, force=False):
        return kllm_service.KllmSnapshot(
            enabled=True,
            configured=True,
            reachable=True,
            stale=False,
            generated_at=datetime.now(UTC),
            age_seconds=0,
            error=None,
            relay_health={"ok": True, "inflight": 0},
            models=[_model("unloaded")],
            backends=[],
            pending=[],
            summary={},
            clients=[],
            traffic={},
            supervisor=False,
            autoscale=False,
        )

    class SessionWrapper:
        async def __aenter__(self):
            return test_db

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(kllm_service, "get_snapshot", fake_snapshot)
    monkeypatch.setattr(worker_module, "AsyncSessionLocal", lambda: SessionWrapper())

    await worker_module._record_kllm_readiness(review.id, "kllm", MODEL)
    refreshed = await get_latest_execution(test_db, review.id)
    readiness = (refreshed.configuration_snapshot or {}).get("kllm_readiness")
    assert readiness["state"] == "unavailable"
    assert readiness["reason_code"] == "manual_unload"


async def test_policy_update_validates_active_session_models(
    admin_client, test_db, monkeypatch
):
    monkeypatch.setattr(config_module.settings, "KLLM_ENABLED", True, raising=False)

    async def fake_snapshot(db, *, force=False):
        return kllm_service.KllmSnapshot(
            enabled=True,
            configured=True,
            reachable=True,
            stale=False,
            generated_at=datetime.now(UTC),
            age_seconds=0,
            error=None,
            relay_health={"ok": True, "inflight": 0},
            models=[_model("unloaded")],
            backends=[],
            pending=[],
            summary={},
            clients=[],
            traffic={},
            supervisor=False,
            autoscale=False,
        )

    monkeypatch.setattr(kllm_service, "get_snapshot", fake_snapshot)
    response = admin_client.put(
        "/api/v1/admin/kllm/autoload",
        json={
            "active_session_autoload": {
                "enabled": True,
                "allowed_models": ["not-a-real-model"],
            }
        },
    )
    assert response.status_code == 400
    assert (
        await kllm_autoload.get_policy(test_db, force=True)
    )["active_session_autoload"]["enabled"] is False
