"""Mocked tests for the admin-controlled kLLM model lifecycle feature.

Nothing here contacts a real kLLM server, loads/stops/rotates a model, or
touches a GPU. Every gateway interaction is monkeypatched at the
``kllm_service`` boundary, and every database interaction uses the in-memory
test database.

Coverage:

* admin-namespace isolation (user JWT cannot reach admin lifecycle routes);
* readiness projection vocabulary;
* the kLLM panel header on state-changing calls;
* composed model unload (in-use refusal, force, partial results);
* the persisted ``kllm_autoload`` policy (two independent, default-disabled
  policies);
* review-demand loading of the exact primary model (no substitution, no
  blind retries);
* best-effort login preload;
* the "loads on demand" catalogue projection;
* worker restoration of the immutable enqueue-time selection snapshot.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select

from app.core import config as config_module
from app.core.auth import get_password_hash
from app.models.audit import AuditLog
from app.models.platform import PlatformSetting
from app.models.provider import ProviderRegistry
from app.models.user import User
from app.queue import worker as worker_module
from app.services import kllm_autoload
from app.services import kllm_service as ks
from app.services.kllm_service import (
    KllmConflictError,
    KllmUnavailableError,
    canonical_model,
)
from app.services.provider_registry import ProviderUnavailableError

MODEL = "qwen3.8-27b"
OTHER_MODEL = "nanbeige4.3-33b-128k"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _model(
    key: str,
    status: str = "loaded",
    *,
    ready: bool = False,
    backend_count: int = 0,
    readiness: str | None = None,
    reason_code: str = "unknown",
) -> ks.KllmModel:
    return ks.KllmModel(
        key=key,
        status=status,
        loaded=status == "loaded",
        ready=ready,
        context_window=131072,
        vision=False,
        tags=[],
        backend_count=backend_count,
        readiness=readiness or ("ready" if ready else "unloaded"),
        reason_code=reason_code,
    )


def _backend(
    account: str,
    model: str | None,
    *,
    healthy: bool = True,
    sessions: int = 0,
    inflight: int = 0,
) -> ks.KllmBackend:
    return ks.KllmBackend(
        id=ks._opaque_id(account),
        model=model,
        healthy=healthy,
        state="running" if healthy else "unhealthy",
        up_s=100,
        left_s=10000,
        draining=False,
        replaced_by=None,
        sessions=sessions,
        inflight=inflight,
        idle_s=0,
        errors_5m=0,
        pinned=False,
        rpm=None,
        quota_used_h=None,
        quota_limit_h=None,
        gpu=None,
    )


def _snapshot(
    *,
    models: list[ks.KllmModel] | None = None,
    backends: list[ks.KllmBackend] | None = None,
    pending: list[dict[str, Any]] | None = None,
    reachable: bool = True,
    stale: bool = False,
) -> ks.KllmSnapshot:
    return ks.KllmSnapshot(
        enabled=True,
        configured=True,
        reachable=reachable,
        stale=stale,
        generated_at=datetime.now(UTC),
        age_seconds=0.0,
        error=None,
        relay_health={"ok": True, "inflight": 0},
        models=models or [],
        backends=backends or [],
        pending=pending or [],
        summary={},
        clients=[],
        traffic={},
        supervisor=False,
        autoscale=False,
    )


async def _seed_managed_provider(db) -> ProviderRegistry:
    provider = ProviderRegistry(
        name="kllm",
        display_name="kLLM",
        slug="kllm",
        litellm_provider="openai",
        default_model=MODEL,
        api_key_min_length=1,
        is_enabled=True,
        status="available",
        is_managed=True,
        allow_key_addition=False,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return provider


@pytest.fixture
def gateway_enabled(monkeypatch):
    monkeypatch.setattr(config_module.settings, "KLLM_ENABLED", True, raising=False)
    return True


# ---------------------------------------------------------------------------
# admin namespace isolation
# ---------------------------------------------------------------------------


def test_admin_kllm_routes_require_the_admin_session(anon_client, user_auth_token):
    assert anon_client.get("/api/v1/admin/kllm").status_code == 401
    # A user JWT is never accepted by the admin namespace.
    assert (
        anon_client.get(
            "/api/v1/admin/kllm",
            headers={"Authorization": f"Bearer {user_auth_token}"},
        ).status_code
        == 401
    )


def test_admin_session_reaches_the_kllm_admin_api(admin_client):
    assert admin_client.get("/api/v1/admin/kllm").status_code == 200


def test_admin_cookie_cannot_drive_user_lifecycle_routes(admin_client):
    """The admin cookie must not authenticate the user namespace."""
    assert admin_client.post("/api/v1/kllm/admin/refresh").status_code == 404
    assert (
        admin_client.post(
            "/api/v1/kllm/admin/models/load",
            json={"model": MODEL, "confirm": True},
        ).status_code
        == 404
    )


def test_user_status_exposes_no_lifecycle_capability(client, monkeypatch):
    async def _false(db):
        return False

    monkeypatch.setattr(config_module.settings, "KLLM_ENABLED", False, raising=False)
    monkeypatch.setattr(ks, "is_enabled", _false)
    monkeypatch.setattr(ks, "is_configured", _false)

    body = client.get("/api/v1/kllm/status").json()
    assert "can_manage" not in body
    assert not any(key.startswith("can_") for key in body)


def test_user_status_strips_backend_control_handles(
    client, admin_client, monkeypatch
):
    monkeypatch.setattr(config_module.settings, "KLLM_ENABLED", True, raising=False)
    snapshot = _snapshot(
        models=[_model(MODEL, "loaded", ready=True, backend_count=1)],
        backends=[_backend("acct-user", MODEL)],
        pending=[{"id": ks._opaque_id("acct-pending"), "model": MODEL, "phase": "starting"}],
    )

    async def fake_snapshot(db, *, force=False):
        return snapshot

    monkeypatch.setattr(ks, "get_snapshot", fake_snapshot)

    user_body = client.get("/api/v1/kllm/status").json()
    assert user_body["backends"][0]["id"] is None
    assert user_body["backends"][0]["replaced_by"] is None
    assert user_body["pending"][0]["id"] is None

    admin_body = admin_client.get("/api/v1/admin/kllm").json()
    assert admin_body["backends"][0]["id"]
    assert admin_body["pending"][0]["id"]


# ---------------------------------------------------------------------------
# readiness projection
# ---------------------------------------------------------------------------


def test_readiness_projection_vocabulary():
    project = ks._readiness_projection

    assert project(
        status="loaded",
        ready=True,
        backend_count=1,
        reachable=True,
        stale=False,
        admin_disabled=False,
    ) == ("ready", "ready")

    assert project(
        status="loading",
        ready=False,
        backend_count=0,
        reachable=True,
        stale=False,
        admin_disabled=False,
    ) == ("loading", "model_loading")

    assert project(
        status="unloaded",
        ready=False,
        backend_count=0,
        reachable=True,
        stale=False,
        admin_disabled=False,
    ) == ("unloaded", "model_unloaded")

    # A "loaded" model without a healthy backend is unavailable, not ready,
    # and must not trigger another load.
    assert project(
        status="loaded",
        ready=False,
        backend_count=0,
        reachable=True,
        stale=False,
        admin_disabled=False,
    ) == ("unavailable", "no_ready_backend")

    assert project(
        status="loaded",
        ready=True,
        backend_count=1,
        reachable=True,
        stale=True,
        admin_disabled=False,
    ) == ("stale", "kllm_state_stale")

    assert project(
        status="loaded",
        ready=True,
        backend_count=1,
        reachable=False,
        stale=False,
        admin_disabled=False,
    ) == ("unavailable", "kllm_unreachable")

    assert project(
        status="loaded",
        ready=True,
        backend_count=1,
        reachable=True,
        stale=False,
        admin_disabled=True,
    ) == ("unavailable", "admin_disabled")


def test_state_changing_calls_carry_the_kllm_panel_header():
    headers = ks._post_headers()
    assert headers["X-Kllm-Panel"] == "1"
    assert headers["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# load request behaviour
# ---------------------------------------------------------------------------


async def test_load_requests_the_exact_canonical_model(test_db, gateway_enabled, monkeypatch):
    await _seed_managed_provider(test_db)
    snapshot = _snapshot(models=[_model(MODEL, "unloaded")])

    async def fake_snapshot(db, *, force=False):
        return snapshot

    posts: list[tuple[str, dict[str, Any]]] = []

    async def fake_post(path, payload, **kwargs):
        posts.append((path, payload))
        return {}

    monkeypatch.setattr(ks, "get_snapshot", fake_snapshot)
    monkeypatch.setattr(ks, "_post_json", fake_post)

    result = await ks.request_model_load(test_db, "qwen")
    assert result["status"] == "loading"
    assert result["model"] == MODEL
    assert posts == [("/admin/api/backends/launch", {"model": MODEL})]


async def test_failed_model_is_never_reloaded(test_db, gateway_enabled, monkeypatch):
    await _seed_managed_provider(test_db)
    snapshot = _snapshot(models=[_model(MODEL, "failed")])

    async def fake_snapshot(db, *, force=False):
        return snapshot

    posts: list[str] = []

    async def fake_post(path, payload, **kwargs):
        posts.append(path)
        return {}

    monkeypatch.setattr(ks, "get_snapshot", fake_snapshot)
    monkeypatch.setattr(ks, "_post_json", fake_post)

    with pytest.raises(KllmConflictError):
        await ks.request_model_load(test_db, MODEL)
    assert posts == []


# ---------------------------------------------------------------------------
# composed model unload
# ---------------------------------------------------------------------------


async def test_unload_stops_every_backend_and_pending_for_the_model(
    test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)
    running = [
        _backend("acct-model-1", MODEL),
        _backend("acct-model-2", MODEL),
        _backend("acct-other", OTHER_MODEL),
    ]
    pending = [{"id": ks._opaque_id("acct-pending"), "model": MODEL, "phase": "starting"}]
    first = _snapshot(
        models=[_model(MODEL, "loaded", ready=True, backend_count=2)],
        backends=running,
        pending=pending,
    )
    second = _snapshot(models=[_model(MODEL, "unloaded")], backends=[], pending=[])

    calls: list[dict[str, Any]] = []
    snapshots = iter([first, second])

    async def fake_snapshot(db, *, force=False):
        try:
            return next(snapshots)
        except StopIteration:
            return second

    async def fake_post(path, payload, **kwargs):
        calls.append(payload)
        return {}

    monkeypatch.setattr(ks, "get_snapshot", fake_snapshot)
    monkeypatch.setattr(ks, "_post_json", fake_post)

    result = await ks.unload_model(test_db, MODEL, confirm=True)

    stopped_accounts = {call["account"] for call in calls}
    assert stopped_accounts == {"acct-model-1", "acct-model-2", "acct-pending"}
    assert "acct-other" not in stopped_accounts
    assert result["status"] == "success"
    assert result["model"] == MODEL
    assert result["stopped"] == 2
    assert result["pending_stopped"] == 1
    assert result["targets"] == 3
    assert result["remaining_backends"] == 0
    assert result["remaining_pending"] == 0


async def test_unload_refuses_while_the_model_is_serving(
    test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)
    snapshot = _snapshot(
        models=[_model(MODEL, "loaded", ready=True, backend_count=1)],
        backends=[_backend("acct-busy", MODEL, sessions=2, inflight=1)],
    )

    async def fake_snapshot(db, *, force=False):
        return snapshot

    posts: list[str] = []

    async def fake_post(path, payload, **kwargs):
        posts.append(path)
        return {}

    monkeypatch.setattr(ks, "get_snapshot", fake_snapshot)
    monkeypatch.setattr(ks, "_post_json", fake_post)

    with pytest.raises(KllmConflictError):
        await ks.unload_model(test_db, MODEL, confirm=True)
    assert posts == []

    forced = await ks.unload_model(test_db, MODEL, confirm=True, force=True)
    assert forced["status"] in ("success", "partial")
    assert posts == ["/admin/api/backends/stop"]


async def test_unload_reports_partial_when_one_stop_fails(
    test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)
    first = _snapshot(
        models=[_model(MODEL, "loaded", ready=True, backend_count=2)],
        backends=[
            _backend("acct-ok", MODEL),
            _backend("acct-fail", MODEL),
        ],
    )
    second = _snapshot(
        models=[_model(MODEL, "loaded", ready=True, backend_count=1)],
        backends=[_backend("acct-fail", MODEL)],
    )
    snapshots = iter([first, second])

    async def fake_snapshot(db, *, force=False):
        try:
            return next(snapshots)
        except StopIteration:
            return second

    async def fake_post(path, payload, **kwargs):
        if payload.get("account") == "acct-fail":
            raise KllmUnavailableError("kLLM is unreachable.")
        return {}

    monkeypatch.setattr(ks, "get_snapshot", fake_snapshot)
    monkeypatch.setattr(ks, "_post_json", fake_post)

    result = await ks.unload_model(test_db, MODEL, confirm=True, force=True)
    assert result["status"] == "partial"
    assert result["stopped"] == 1
    assert result["errors"] == 1
    assert result["remaining_backends"] == 1


async def test_unload_requires_confirmation(test_db, gateway_enabled, monkeypatch):
    await _seed_managed_provider(test_db)

    async def fake_snapshot(db, *, force=False):
        return _snapshot(models=[_model(MODEL, "unloaded")])

    monkeypatch.setattr(ks, "get_snapshot", fake_snapshot)
    with pytest.raises(KllmConflictError):
        await ks.unload_model(test_db, MODEL)


# ---------------------------------------------------------------------------
# admin API: unload + policy
# ---------------------------------------------------------------------------


async def test_admin_unload_is_audited_and_requires_confirmation(
    admin_client, test_db, monkeypatch
):
    monkeypatch.setattr(config_module.settings, "KLLM_ENABLED", True, raising=False)

    async def fake_unload(db, model, *, confirm=False, force=False):
        if not confirm:
            raise KllmConflictError("This action requires explicit confirmation.")
        return {
            "status": "success",
            "model": model,
            "stopped": 1,
            "targets": 1,
            "remaining_backends": 0,
            "remaining_pending": 0,
            "errors": 0,
            "sessions_affected": 0,
            "inflight_affected": 0,
        }

    monkeypatch.setattr(ks, "unload_model", fake_unload)

    denied = admin_client.post(
        "/api/v1/admin/kllm/models/unload",
        json={"model": MODEL, "confirm": False},
    )
    assert denied.status_code == 409

    ok = admin_client.post(
        "/api/v1/admin/kllm/models/unload",
        json={"model": MODEL, "confirm": True},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "success"

    rows = (
        (
            await test_db.execute(
                select(AuditLog).where(
                    AuditLog.action == "admin.kllm_model_unload"
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows
    assert all("password" not in str(row.details).lower() for row in rows)


async def test_autoload_policy_defaults_to_disabled(test_db):
    policy = await kllm_autoload.get_policy(test_db, force=True)
    assert policy["review_autoload"]["enabled"] is False
    assert policy["review_autoload"]["allowed_models"] == []
    assert policy["login_preload"]["enabled"] is False
    assert policy["login_preload"]["allowed_models"] == []


async def test_admin_can_persist_the_autoload_policy(
    admin_client, test_db, monkeypatch
):
    monkeypatch.setattr(config_module.settings, "KLLM_ENABLED", True, raising=False)

    async def fake_snapshot(db, *, force=False):
        return _snapshot(models=[_model(MODEL, "unloaded")])

    monkeypatch.setattr(ks, "get_snapshot", fake_snapshot)

    response = admin_client.put(
        "/api/v1/admin/kllm/autoload",
        json={
            "review_autoload": {"enabled": True, "allowed_models": [MODEL]},
            "login_preload": {"enabled": False, "allowed_models": []},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["review_autoload"]["enabled"] is True
    assert body["review_autoload"]["allowed_models"] == [MODEL]
    # The two policies are independent.
    assert body["login_preload"]["enabled"] is False
    assert body["login_preload"]["allowed_models"] == []

    # Persisted in platform_settings under the agreed key (no migration).
    row = (
        await test_db.execute(
            select(PlatformSetting).where(
                PlatformSetting.key == kllm_autoload.KLLM_AUTOLOAD_KEY
            )
        )
    ).scalars().first()
    assert row is not None
    assert row.value["review_autoload"]["enabled"] is True

    read_back = admin_client.get("/api/v1/admin/kllm/autoload").json()
    assert read_back["review_autoload"]["allowed_models"] == [MODEL]


async def test_admin_policy_audit_includes_all_three_groups(
    admin_client, test_db, monkeypatch
):
    monkeypatch.setattr(config_module.settings, "KLLM_ENABLED", True, raising=False)

    async def fake_snapshot(db, *, force=False):
        return _snapshot(models=[_model(MODEL, "unloaded")])

    monkeypatch.setattr(ks, "get_snapshot", fake_snapshot)

    response = admin_client.put(
        "/api/v1/admin/kllm/autoload",
        json={
            "active_session_autoload": {
                "enabled": True,
                "allowed_models": [MODEL],
            }
        },
    )
    assert response.status_code == 200, response.text

    rows = (
        (
            await test_db.execute(
                select(AuditLog).where(
                    AuditLog.action == "admin.kllm_autoload_updated"
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows
    details = rows[-1].details
    for group in (
        "review_autoload",
        "login_preload",
        "active_session_autoload",
    ):
        assert group in details["prior"]
        assert group in details["new"]
    assert details["new"]["active_session_autoload"]["enabled"] is True
    assert details["new"]["active_session_autoload"]["allowed_models"] == [MODEL]
    assert details["prior"]["version"] != details["new"]["version"]
    lowered = str(details).lower()
    for sensitive in ("jti", "token", "session_id", "password"):
        assert sensitive not in lowered


async def test_admin_autoload_policy_rejects_unknown_models(
    admin_client, monkeypatch
):
    monkeypatch.setattr(config_module.settings, "KLLM_ENABLED", True, raising=False)

    async def fake_snapshot(db, *, force=False):
        return _snapshot(models=[_model(MODEL, "unloaded")])

    monkeypatch.setattr(ks, "get_snapshot", fake_snapshot)

    response = admin_client.put(
        "/api/v1/admin/kllm/autoload",
        json={
            "review_autoload": {
                "enabled": True,
                "allowed_models": ["not-a-real-model"],
            }
        },
    )
    assert response.status_code == 400


async def test_autoload_policy_update_conflicts_on_stale_version(
    admin_client, test_db, monkeypatch
):
    monkeypatch.setattr(config_module.settings, "KLLM_ENABLED", True, raising=False)

    async def fake_snapshot(db, *, force=False):
        return _snapshot(models=[_model(MODEL, "unloaded")])

    monkeypatch.setattr(ks, "get_snapshot", fake_snapshot)

    first = admin_client.put(
        "/api/v1/admin/kllm/autoload",
        json={"review_autoload": {"enabled": True, "allowed_models": [MODEL]}},
    )
    assert first.status_code == 200
    version = first.json()["version"]

    stale = admin_client.put(
        "/api/v1/admin/kllm/autoload",
        json={
            "review_autoload": {"enabled": False, "allowed_models": []},
            "version": version - 1,
        },
    )
    assert stale.status_code == 409


# ---------------------------------------------------------------------------
# review-demand loading
# ---------------------------------------------------------------------------


def _allow_review_autoload(policy: dict[str, Any], model: str) -> None:
    policy["review_autoload"] = {
        "enabled": True,
        "allowed_models": [model],
    }


async def test_review_autoload_loads_the_exact_primary_model(
    test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)
    policy = await kllm_autoload.get_policy(test_db, force=True)
    _allow_review_autoload(policy, MODEL)

    async def fake_policy(db=None, *, force=True):
        return _policy(policy)

    monkeypatch.setattr(kllm_autoload, "get_policy", fake_policy)
    monkeypatch.setattr(kllm_autoload, "_POLL_INTERVAL_SECONDS", 0.01)

    state = {"loaded": False}
    requested: list[str] = []

    async def fake_snapshot(db, *, force=False):
        if state["loaded"]:
            return _snapshot(
                models=[_model(MODEL, "loaded", ready=True, backend_count=1)]
            )
        return _snapshot(models=[_model(MODEL, "unloaded")])

    async def fake_request_load(db, model):
        requested.append(model)
        state["loaded"] = True
        return {"status": "loading", "model": model}

    monkeypatch.setattr(ks, "get_snapshot", fake_snapshot)
    monkeypatch.setattr(ks, "request_model_load", fake_request_load)

    result = await kllm_autoload.ensure_model_ready_with_autoload(test_db, MODEL)
    assert result.ready is True
    # Exactly one load request, for exactly the mapped model.
    assert requested == [MODEL]


async def test_review_autoload_wait_is_cancellable(
    test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)
    policy = await kllm_autoload.get_policy(test_db, force=True)
    _allow_review_autoload(policy, MODEL)

    async def fake_policy(db=None, *, force=True):
        return _policy(policy)

    monkeypatch.setattr(kllm_autoload, "get_policy", fake_policy)

    async def fake_snapshot(db, *, force=False):
        return _snapshot(models=[_model(MODEL, "loading")])

    requested: list[str] = []

    async def fake_request_load(db, model):
        requested.append(model)
        return {"status": "loading", "model": model}

    monkeypatch.setattr(ks, "get_snapshot", fake_snapshot)
    monkeypatch.setattr(ks, "request_model_load", fake_request_load)

    async def cancelled() -> bool:
        return True

    with pytest.raises(asyncio.CancelledError):
        await kllm_autoload.ensure_model_ready_with_autoload(
            test_db,
            MODEL,
            cancel_check=cancelled,
        )
    assert requested == []


async def test_review_autoload_refuses_an_unapproved_model(
    test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)

    async def fake_policy(db=None, *, force=True):
        return _policy({})

    monkeypatch.setattr(kllm_autoload, "get_policy", fake_policy)

    requested: list[str] = []

    async def fake_snapshot(db, *, force=False):
        return _snapshot(models=[_model(MODEL, "unloaded")])

    async def fake_request_load(db, model):
        requested.append(model)
        return {"status": "loading", "model": model}

    monkeypatch.setattr(ks, "get_snapshot", fake_snapshot)
    monkeypatch.setattr(ks, "request_model_load", fake_request_load)

    with pytest.raises(KllmUnavailableError):
        await kllm_autoload.ensure_model_ready_with_autoload(test_db, MODEL)
    assert requested == []


async def test_review_autoload_never_substitutes_another_model(
    test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)
    policy = await kllm_autoload.get_policy(test_db, force=True)
    _allow_review_autoload(policy, MODEL)

    async def fake_policy(db=None, *, force=True):
        return _policy(policy)

    monkeypatch.setattr(kllm_autoload, "get_policy", fake_policy)
    monkeypatch.setattr(kllm_autoload, "_POLL_INTERVAL_SECONDS", 0.01)

    state = {"loaded": False}
    requested: list[str] = []

    async def fake_snapshot(db, *, force=False):
        if state["loaded"]:
            return _snapshot(
                models=[_model(MODEL, "loaded", ready=True, backend_count=1)]
            )
        return _snapshot(
            models=[_model(MODEL, "unloaded"), _model(OTHER_MODEL, "unloaded")]
        )

    async def fake_request_load(db, model):
        requested.append(model)
        state["loaded"] = True
        return {"status": "loading", "model": model}

    monkeypatch.setattr(ks, "get_snapshot", fake_snapshot)
    monkeypatch.setattr(ks, "request_model_load", fake_request_load)

    await kllm_autoload.ensure_model_ready_with_autoload(test_db, MODEL)
    assert requested == [MODEL]
    assert OTHER_MODEL not in requested


async def test_failed_model_is_not_retried_by_review_autoload(
    test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)
    policy = await kllm_autoload.get_policy(test_db, force=True)
    _allow_review_autoload(policy, MODEL)

    async def fake_policy(db=None, *, force=True):
        return _policy(policy)

    monkeypatch.setattr(kllm_autoload, "get_policy", fake_policy)

    requested: list[str] = []

    async def fake_snapshot(db, *, force=False):
        return _snapshot(models=[_model(MODEL, "failed")])

    async def fake_request_load(db, model):
        requested.append(model)
        return {"status": "loading", "model": model}

    monkeypatch.setattr(ks, "get_snapshot", fake_snapshot)
    monkeypatch.setattr(ks, "request_model_load", fake_request_load)

    with pytest.raises(KllmConflictError):
        await kllm_autoload.ensure_model_ready_with_autoload(test_db, MODEL)
    assert requested == []


def _policy(policy: dict[str, Any]) -> dict[str, Any]:
    """Normalize a policy dict the way the service would."""
    normalized = dict(policy)
    normalized.setdefault("review_autoload", {"enabled": False, "allowed_models": []})
    normalized.setdefault("login_preload", {"enabled": False, "allowed_models": []})
    normalized.setdefault("load_timeout_seconds", 1200)
    normalized.setdefault("max_concurrent_loads", 1)
    normalized.setdefault("login_preload_cooldown_seconds", 300)
    return normalized


# ---------------------------------------------------------------------------
# login preload
# ---------------------------------------------------------------------------


async def test_login_preload_only_requests_approved_models(monkeypatch):
    requested: list[str] = []

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def get_bind(self):
            return type("Bind", (), {"dialect": type("Dialect", (), {"name": "sqlite"})})()

    async def fake_get_policy(db=None, *, force=True):
        return _policy(
            {
                "review_autoload": {"enabled": False, "allowed_models": []},
                "login_preload": {
                    "enabled": True,
                    "allowed_models": [MODEL],
                },
                "login_preload_cooldown_seconds": 0,
            }
        )

    async def fake_read_model(db, model):
        return _model(model, "unloaded")

    async def fake_request_load_once(db, model, policy):
        requested.append(model)
        return {"status": "loading", "model": model}

    monkeypatch.setattr(kllm_autoload, "AsyncSessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(kllm_autoload, "get_policy", fake_get_policy)
    monkeypatch.setattr(kllm_autoload, "_read_model", fake_read_model)
    monkeypatch.setattr(kllm_autoload, "_request_load_once", fake_request_load_once)
    monkeypatch.setattr(kllm_autoload, "_login_last_request", {})

    async def fake_assert_load_allowed(db, model):
        return None

    monkeypatch.setattr(
        kllm_autoload, "_assert_load_allowed", fake_assert_load_allowed
    )

    await kllm_autoload.preload_after_login(uuid.uuid4())
    assert requested == [MODEL]


async def test_login_preload_fails_open(monkeypatch):
    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    async def fake_get_policy(db=None, *, force=True):
        raise RuntimeError("policy store unavailable")

    monkeypatch.setattr(kllm_autoload, "AsyncSessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(kllm_autoload, "get_policy", fake_get_policy)

    # Never raises: authentication must not depend on the preload.
    await kllm_autoload.preload_after_login(uuid.uuid4())


async def test_login_registers_the_preload_only_after_a_successful_sign_in(
    client, test_db, monkeypatch
):
    from app.middleware.rate_limit import limiter

    limiter.reset()
    user = User(
        id=uuid.uuid4(),
        name="Login User",
        email="login@example.com",
        role="user",
        is_verified=True,
        password_hash=get_password_hash("correct-horse-battery"),
    )
    test_db.add(user)
    await test_db.commit()

    scheduled: list[Any] = []
    monkeypatch.setattr(
        "app.api.v1.endpoints.auth.schedule_login_preload",
        lambda background_tasks, user_id: scheduled.append(user_id),
    )

    denied = client.post(
        "/api/v1/auth/login",
        data={"username": user.email, "password": "wrong-password"},
    )
    assert denied.status_code == 401
    assert scheduled == []

    ok = client.post(
        "/api/v1/auth/login",
        data={"username": user.email, "password": "correct-horse-battery"},
    )
    assert ok.status_code == 200
    assert scheduled == [user.id]


# ---------------------------------------------------------------------------
# catalogue projection
# ---------------------------------------------------------------------------


async def test_catalogue_marks_approved_unloaded_models_as_loads_on_demand(
    test_db, gateway_enabled, monkeypatch
):
    async def fake_snapshot(db, *, force=False):
        return _snapshot(
            models=[
                _model(MODEL, "loaded", ready=True, backend_count=1),
                _model(OTHER_MODEL, "unloaded"),
            ]
        )

    async def fake_get_policy(db=None, *, force=True):
        return _policy(
            {
                "review_autoload": {
                    "enabled": True,
                    "allowed_models": [OTHER_MODEL],
                }
            }
        )

    monkeypatch.setattr(ks, "get_snapshot", fake_snapshot)
    monkeypatch.setattr(kllm_autoload, "get_policy", fake_get_policy)

    rows = await ks.get_model_options(test_db)
    by_name = {row["model_name"]: row for row in rows}
    assert set(by_name) == {MODEL, OTHER_MODEL}
    assert by_name[MODEL]["loads_on_demand"] is False
    assert by_name[MODEL]["readiness"] == "ready"
    assert by_name[OTHER_MODEL]["loads_on_demand"] is True
    assert by_name[OTHER_MODEL]["readiness"] == "unloaded"


async def test_catalogue_hides_unapproved_unloaded_models(
    test_db, gateway_enabled, monkeypatch
):
    async def fake_snapshot(db, *, force=False):
        return _snapshot(
            models=[
                _model(MODEL, "loaded", ready=True, backend_count=1),
                _model(OTHER_MODEL, "unloaded"),
            ]
        )

    async def fake_get_policy(db=None, *, force=True):
        return _policy({"review_autoload": {"enabled": True, "allowed_models": []}})

    monkeypatch.setattr(ks, "get_snapshot", fake_snapshot)
    monkeypatch.setattr(kllm_autoload, "get_policy", fake_get_policy)

    rows = await ks.get_model_options(test_db)
    assert [row["model_name"] for row in rows] == [MODEL]


async def test_selectable_gate_requires_policy_for_an_unloaded_model(
    test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)

    async def fake_snapshot(db, *, force=False):
        return _snapshot(models=[_model(MODEL, "unloaded")])

    async def fake_get_policy(db=None, *, force=True):
        return _policy({"review_autoload": {"enabled": False, "allowed_models": []}})

    monkeypatch.setattr(ks, "get_snapshot", fake_snapshot)
    monkeypatch.setattr(kllm_autoload, "get_policy", fake_get_policy)

    with pytest.raises(KllmUnavailableError):
        await ks.ensure_model_selectable(test_db, MODEL)

    async def allowing_policy(db=None, *, force=True):
        return _policy(
            {
                "review_autoload": {
                    "enabled": True,
                    "allowed_models": [MODEL],
                }
            }
        )

    monkeypatch.setattr(kllm_autoload, "get_policy", allowing_policy)
    match = await ks.ensure_model_selectable(test_db, MODEL)
    assert match.key == MODEL


def test_selection_api_exposes_sanitized_kllm_readiness():
    from app.services.review_selection import selection_api_fields_from_values

    fields = selection_api_fields_from_values(
        {
            "kllm_readiness": {
                "model": MODEL,
                "state": "loading_model",
                "reason_code": "model_loading",
                "checked_at": "2026-11-21T00:00:00+00:00",
                "secret": "must-not-leak",
            }
        },
        "kllm",
        MODEL,
        "running",
        None,
        {},
    )

    assert fields["kllm_readiness"] == {
        "model": MODEL,
        "state": "loading_model",
        "reason_code": "model_loading",
        "checked_at": "2026-11-21T00:00:00+00:00",
    }


async def test_preflight_reads_are_forced_when_requested(
    test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)
    seen: list[bool] = []

    async def fake_snapshot(db, *, force=False):
        seen.append(bool(force))
        return _snapshot(models=[_model(MODEL, "loaded", ready=True, backend_count=1)])

    monkeypatch.setattr(ks, "get_snapshot", fake_snapshot)

    await ks.ensure_model_available(test_db, MODEL)
    assert seen == [True]
    seen.clear()

    await ks.ensure_model_ready(test_db, MODEL)
    assert seen == [False]
    seen.clear()

    await ks.ensure_model_ready(test_db, MODEL, force=True)
    assert seen == [True]


def test_canonical_model_maps_known_aliases():
    assert canonical_model("sonnet") == MODEL
    assert canonical_model("openai/sonnet") == MODEL
    assert canonical_model(MODEL) == MODEL


# ---------------------------------------------------------------------------
# worker: immutable selection snapshot
# ---------------------------------------------------------------------------


async def test_worker_restores_the_enqueued_selection_snapshot(
    test_db, monkeypatch
):
    from app.services.review_selection import (
        ResolvedSelection,
        merge_configuration_snapshot,
    )

    captured = ResolvedSelection(
        provider="kllm",
        provider_slug="kllm",
        provider_name="kLLM",
        model=MODEL,
        api_key_id=None,
        source="repo_config",
        repository_mapping_status="mapped",
        repository_provider="kllm",
        repository_model=MODEL,
    )
    snapshot = merge_configuration_snapshot({}, captured)["selection"]

    class _Execution:
        configuration_snapshot = {"selection": snapshot}  # noqa: RUF012
        provider = "kllm"
        model = MODEL
        api_key_id = None

    calls: list[str] = []

    async def fake_resolve(db, user_id, db_repo):
        calls.append("resolve")
        return ResolvedSelection(
            provider="other-provider",
            provider_slug="other-provider",
            provider_name="Other",
            model="other-model",
            api_key_id=None,
            source="user_routing",
            repository_mapping_status="mapped",
            repository_provider="kllm",
            repository_model=MODEL,
        )

    async def fake_validate(db, selection):
        calls.append("validate")

    monkeypatch.setattr(
        "app.services.review_selection.resolve_selection", fake_resolve
    )
    monkeypatch.setattr(
        "app.services.review_selection.validate_selection", fake_validate
    )

    selection = await worker_module._resolve_execution_selection(
        test_db, _Execution(), str(uuid.uuid4()), None
    )

    # The snapshot wins: the worker never re-resolves the current mapping.
    assert selection.provider == "kllm"
    assert selection.model == MODEL
    assert calls == ["validate"]


async def test_worker_keeps_snapshot_on_transient_kllm_failure(
    test_db, monkeypatch
):
    from app.services.review_selection import (
        ResolvedSelection,
        merge_configuration_snapshot,
    )

    captured = ResolvedSelection(
        provider="kllm",
        provider_slug="kllm",
        provider_name="kLLM",
        model=MODEL,
        api_key_id=None,
        source="repo_config",
        repository_mapping_status="mapped",
        repository_provider="kllm",
        repository_model=MODEL,
    )
    snapshot = merge_configuration_snapshot({}, captured)["selection"]

    class _Execution:
        configuration_snapshot = {"selection": snapshot}  # noqa: RUF012
        provider = "kllm"
        model = MODEL
        api_key_id = None

    calls: list[str] = []

    async def fake_resolve(db, user_id, db_repo):
        calls.append("resolve")
        raise AssertionError("transient state must not re-resolve selection")

    async def fake_validate(db, selection):
        calls.append("validate")
        raise ProviderUnavailableError(
            "kllm", "kLLM is unreachable.", definitive=False
        )

    monkeypatch.setattr(
        "app.services.review_selection.resolve_selection", fake_resolve
    )
    monkeypatch.setattr(
        "app.services.review_selection.validate_selection", fake_validate
    )

    selection = await worker_module._resolve_execution_selection(
        test_db, _Execution(), str(uuid.uuid4()), None
    )

    assert selection.provider == "kllm"
    assert selection.model == MODEL
    assert calls == ["validate"]


async def test_worker_re_resolves_only_after_definitive_failure(
    test_db, monkeypatch
):
    from app.models.execution import ReviewExecution
    from app.services.review_selection import (
        ResolvedSelection,
        merge_configuration_snapshot,
    )

    captured = ResolvedSelection(
        provider="kllm",
        provider_slug="kllm",
        provider_name="kLLM",
        model=MODEL,
        api_key_id=None,
        source="repo_config",
        repository_mapping_status="mapped",
        repository_provider="kllm",
        repository_model=MODEL,
    )
    snapshot = merge_configuration_snapshot({}, captured)["selection"]
    execution = ReviewExecution(
        review_id=uuid.uuid4(),
        execution_number=1,
        configuration_snapshot={"selection": snapshot},
        provider="kllm",
        model=MODEL,
        api_key_id=None,
    )

    calls: list[str] = []

    async def fake_resolve(db, user_id, db_repo):
        calls.append("resolve")
        return ResolvedSelection(
            provider="fallback",
            provider_slug="fallback",
            provider_name="Fallback",
            model="fallback-model",
            api_key_id=None,
            source="user_routing",
            repository_mapping_status="mapped",
            repository_provider="kllm",
            repository_model=MODEL,
        )

    async def fake_validate(db, selection):
        calls.append("validate")
        raise ProviderUnavailableError(
            "kllm", "Model failed to load.", definitive=True
        )

    monkeypatch.setattr(
        "app.services.review_selection.resolve_selection", fake_resolve
    )
    monkeypatch.setattr(
        "app.services.review_selection.validate_selection", fake_validate
    )

    selection = await worker_module._resolve_execution_selection(
        test_db, execution, str(uuid.uuid4()), None
    )

    assert selection.provider == "fallback"
    assert selection.model == "fallback-model"
    assert calls == ["validate", "resolve"]
