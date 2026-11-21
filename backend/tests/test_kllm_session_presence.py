"""Mocked tests for active-session kLLM auto-loading and manual precedence.

No test in this module contacts kLLM, loads/stops a model, or touches a GPU.
All gateway interactions are monkeypatched at the service boundary.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.core import config as config_module
from app.core.auth import create_access_token, decode_access_token
from app.models.platform import ModelOverride, PlatformSetting
from app.models.provider import ProviderRegistry
from app.models.user_presence import UserPresence
from app.services import kllm_autoload, kllm_service, user_presence
from app.services.kllm_service import KllmConflictError, KllmUnavailableError

MODEL = "qwen3.8-27b"


@pytest.fixture
def gateway_enabled(monkeypatch):
    monkeypatch.setattr(config_module.settings, "KLLM_ENABLED", True, raising=False)
    return True


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


def _model(status: str = "unloaded", *, ready: bool = False):
    return kllm_service.KllmModel(
        key=MODEL,
        status=status,
        loaded=status == "loaded",
        ready=ready,
        context_window=131072,
        vision=False,
        tags=[],
        backend_count=1 if ready else 0,
        readiness="ready" if ready else "unloaded",
        reason_code="ready" if ready else "model_unloaded",
    )


def _policy(group: str, models: list[str] | None = None) -> dict[str, Any]:
    return kllm_autoload._normalize_policy(
        {
            group: {
                "enabled": True,
                "allowed_models": models if models is not None else [MODEL],
            },
            "load_timeout_seconds": 60,
            "max_concurrent_loads": 1,
            "login_preload_cooldown_seconds": 0,
        },
        1,
    )


def _payload(*, expired: bool = False) -> dict[str, Any]:
    token = create_access_token(
        subject=str(uuid.uuid4()),
        expires_delta=timedelta(seconds=-1 if expired else 3600),
    )
    return decode_access_token(token)


# ---------------------------------------------------------------------------
# presence lifecycle
# ---------------------------------------------------------------------------


async def test_session_heartbeat_creates_one_row_per_browser_tab(
    anon_client, test_db, mock_user, user_auth_token, monkeypatch
):
    async def fake_reconcile(db):
        return []

    monkeypatch.setattr(kllm_autoload, "reconcile_session_models", fake_reconcile)
    headers = {"Authorization": f"Bearer {user_auth_token}"}
    first = str(uuid.uuid4())
    second = str(uuid.uuid4())

    for session_id in (first, second):
        response = anon_client.post(
            "/api/v1/kllm/session/heartbeat",
            headers=headers,
            json={"client_session_id": session_id, "active": True},
        )
        assert response.status_code == 200, response.text
        assert response.json()["session"]["active"] is True

    rows = (
        (await test_db.execute(select(UserPresence))).scalars().all()
    )
    assert len(rows) == 2
    assert all(row.token_jti_hash and row.token_jti_hash != user_auth_token for row in rows)
    assert all(row.user_id == mock_user.id for row in rows)

    # Repeating a heartbeat updates the same row rather than inserting another.
    anon_client.post(
        "/api/v1/kllm/session/heartbeat",
        headers=headers,
        json={"client_session_id": first, "active": True},
    )
    rows = (await test_db.execute(select(UserPresence))).scalars().all()
    assert len(rows) == 2


async def test_inactive_and_stale_presence_are_not_active_sessions(test_db, mock_user):
    payload = _payload()
    session_id = str(uuid.uuid4())
    await user_presence.upsert_heartbeat(
        test_db,
        user_id=mock_user.id,
        payload=payload,
        client_session_id=session_id,
        active=False,
    )
    await test_db.commit()
    assert await user_presence.has_active_session(test_db) is False

    stale_at = datetime.now(UTC) - timedelta(seconds=user_presence.ACTIVE_TTL_SECONDS + 30)
    await user_presence.upsert_heartbeat(
        test_db,
        user_id=mock_user.id,
        payload=payload,
        client_session_id=session_id,
        active=True,
        now=stale_at,
    )
    await test_db.commit()
    assert await user_presence.has_active_session(test_db) is False

    assert user_presence.public_status(None)["active"] is False


async def test_expired_token_cannot_create_presence(anon_client):
    token = create_access_token(
        subject=str(uuid.uuid4()), expires_delta=timedelta(seconds=-1)
    )
    response = anon_client.post(
        "/api/v1/kllm/session/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={"client_session_id": str(uuid.uuid4()), "active": True},
    )
    assert response.status_code == 401


async def test_session_end_marks_only_one_tab_inactive(
    anon_client, test_db, mock_user, user_auth_token, monkeypatch
):
    async def fake_reconcile(db):
        return []

    monkeypatch.setattr(kllm_autoload, "reconcile_session_models", fake_reconcile)
    headers = {"Authorization": f"Bearer {user_auth_token}"}
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    for session_id in (first, second):
        assert (
            anon_client.post(
                "/api/v1/kllm/session/heartbeat",
                headers=headers,
                json={"client_session_id": session_id, "active": True},
            ).status_code
            == 200
        )
    response = anon_client.post(
        "/api/v1/kllm/session/end",
        headers=headers,
        json={"client_session_id": first, "active": False},
    )
    assert response.status_code == 200
    assert response.json()["active"] is False
    assert await user_presence.has_active_session(test_db) is True

    rows = (await test_db.execute(select(UserPresence))).scalars().all()
    assert {row.active for row in rows} == {True, False}


async def test_logout_clears_all_presence_for_the_user(
    anon_client, test_db, mock_user, user_auth_token, monkeypatch
):
    async def fake_reconcile(db):
        return []

    monkeypatch.setattr(kllm_autoload, "reconcile_session_models", fake_reconcile)
    headers = {"Authorization": f"Bearer {user_auth_token}"}
    for _ in range(2):
        assert (
            anon_client.post(
                "/api/v1/kllm/session/heartbeat",
                headers=headers,
                json={"client_session_id": str(uuid.uuid4()), "active": True},
            ).status_code
            == 200
        )
    assert await user_presence.has_active_session(test_db) is True

    response = anon_client.post("/api/v1/auth/logout", headers=headers)
    assert response.status_code == 200
    assert (
        await test_db.execute(select(UserPresence).where(UserPresence.user_id == mock_user.id))
    ).scalars().all() == []


# ---------------------------------------------------------------------------
# active-session autoload
# ---------------------------------------------------------------------------


async def test_session_autoload_requires_an_active_session(
    test_db, gateway_enabled, mock_user, monkeypatch
):
    await _seed_managed_provider(test_db)
    await kllm_autoload.update_policy(
        test_db,
        {"active_session_autoload": {"enabled": True, "allowed_models": [MODEL]}},
    )
    await test_db.commit()
    monkeypatch.setattr(kllm_service, "is_enabled", _enabled)
    monkeypatch.setattr(kllm_autoload, "_read_model", _read_unloaded)

    requested: list[str] = []

    async def fake_request(db, model, policy):
        requested.append(model)
        return {"status": "loading", "model": model}

    monkeypatch.setattr(kllm_autoload, "_request_load_once", fake_request)

    assert await kllm_autoload.reconcile_session_models(test_db) == []
    assert requested == []

    await user_presence.upsert_heartbeat(
        test_db,
        user_id=mock_user.id,
        payload=_payload(),
        client_session_id=str(uuid.uuid4()),
        active=True,
    )
    await test_db.commit()
    results = await kllm_autoload.reconcile_session_models(test_db)
    assert requested == [MODEL]
    assert results[0]["state"] == "loading_model"


async def test_active_session_reloads_after_kllm_idle_retirement(
    test_db, gateway_enabled, mock_user, monkeypatch
):
    await _seed_managed_provider(test_db)
    await kllm_autoload.update_policy(
        test_db,
        {"active_session_autoload": {"enabled": True, "allowed_models": [MODEL]}},
    )
    await test_db.commit()
    await user_presence.upsert_heartbeat(
        test_db,
        user_id=mock_user.id,
        payload=_payload(),
        client_session_id=str(uuid.uuid4()),
        active=True,
    )
    await test_db.commit()

    state = {"ready": True}
    monkeypatch.setattr(kllm_service, "is_enabled", _enabled)

    async def fake_read(db, model):
        return _model("loaded", ready=state["ready"]) if state["ready"] else _model("unloaded")

    monkeypatch.setattr(kllm_autoload, "_read_model", fake_read)
    requested: list[str] = []

    async def fake_request(db, model, policy):
        requested.append(model)
        state["ready"] = True
        return {"status": "loading", "model": model}

    monkeypatch.setattr(kllm_autoload, "_request_load_once", fake_request)

    first = await kllm_autoload.reconcile_session_models(test_db)
    assert first[0]["state"] == "ready"
    assert requested == []

    state["ready"] = False
    second = await kllm_autoload.reconcile_session_models(test_db)
    assert second[0]["state"] == "loading_model"
    assert requested == [MODEL]


async def _enabled(db):
    return True


async def _read_unloaded(db, model):
    return _model("unloaded")


# ---------------------------------------------------------------------------
# manual-unload precedence
# ---------------------------------------------------------------------------


async def test_manual_unload_block_stops_every_automatic_path(
    test_db, gateway_enabled, mock_user, monkeypatch
):
    await _seed_managed_provider(test_db)
    await kllm_autoload.update_policy(
        test_db,
        {
            "review_autoload": {"enabled": True, "allowed_models": [MODEL]},
            "login_preload": {"enabled": True, "allowed_models": [MODEL]},
            "active_session_autoload": {"enabled": True, "allowed_models": [MODEL]},
        },
    )
    await kllm_autoload.set_manual_block(test_db, MODEL, admin_id=uuid.uuid4())
    await user_presence.upsert_heartbeat(
        test_db,
        user_id=mock_user.id,
        payload=_payload(),
        client_session_id=str(uuid.uuid4()),
        active=True,
    )
    await test_db.commit()

    with pytest.raises(KllmConflictError) as exc:
        await kllm_autoload._assert_load_allowed(test_db, MODEL)
    assert exc.value.reason_code == "manual_unload"

    monkeypatch.setattr(kllm_service, "is_enabled", _enabled)
    monkeypatch.setattr(kllm_autoload, "_read_model", _read_unloaded)
    requested: list[str] = []

    async def forbidden_request(db, model, policy):
        requested.append(model)
        raise AssertionError("manually unloaded models must never reload")

    monkeypatch.setattr(kllm_autoload, "_request_load_once", forbidden_request)

    with pytest.raises(KllmConflictError):
        await kllm_autoload.ensure_model_ready_with_autoload(test_db, MODEL)

    session_results = await kllm_autoload.reconcile_session_models(test_db)
    assert session_results[0]["reason_code"] == "manual_unload"

    class SessionWrapper:
        async def __aenter__(self):
            return test_db

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(kllm_autoload, "AsyncSessionLocal", lambda: SessionWrapper())
    await kllm_autoload.preload_after_login(uuid.uuid4())
    assert requested == []


async def test_manual_load_clears_block(test_db, gateway_enabled, monkeypatch):
    await _seed_managed_provider(test_db)
    await kllm_autoload.set_manual_block(test_db, MODEL, admin_id=uuid.uuid4())
    await test_db.commit()

    async def fake_load(db, model, *, confirm):
        return {"status": "loading", "model": model}

    monkeypatch.setattr(kllm_service, "load_model", fake_load)
    result = await kllm_autoload.manual_load_model(
        test_db, MODEL, confirm=True, admin_id=uuid.uuid4()
    )
    assert result["manual_block_cleared"] is True
    assert await kllm_autoload.is_manually_blocked(test_db, MODEL) is False


async def test_explicit_unload_commits_block_before_stopping_backends(
    test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)
    monkeypatch.setattr(kllm_service, "get_default_model", _default_model_none)
    observed: list[bool] = []

    async def fake_unload(db, model, *, confirm, force):
        observed.append(await kllm_autoload.is_manually_blocked(db, model))
        return {"status": "success", "model": model}

    monkeypatch.setattr(kllm_service, "unload_model", fake_unload)
    result = await kllm_autoload.manual_unload_model(
        test_db, MODEL, confirm=True, force=False, admin_id=uuid.uuid4()
    )
    assert observed == [True]
    assert result["automatic_loading_blocked"] is True


async def _default_model_none(db):
    return None


async def test_default_model_unload_conflicts_with_always_on(
    test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)
    monkeypatch.setattr(kllm_service, "get_default_model", _default_model)

    async def fake_config():
        return {
            "reachable": True,
            "size": 2,
            "enabled": True,
            "verified": True,
            "autoscale_min_backends": 2,
            "desired_pool": 0,
        }

    monkeypatch.setattr(kllm_service, "get_autoscale_config", fake_config)

    with pytest.raises(KllmConflictError) as exc:
        await kllm_autoload.manual_unload_model(
            test_db, MODEL, confirm=True, force=False, admin_id=uuid.uuid4()
        )
    assert exc.value.reason_code == "always_on_conflict"

    disabled: list[int] = []

    async def fake_set_keep(db, size, *, confirm):
        disabled.append(size)
        return {
            "status": "always_on_disabled",
            "size": size,
            "verified": True,
            "effectively_disabled": True,
            "effective_min_backends": 0,
        }

    async def fake_unload(db, model, *, confirm, force):
        return {"status": "success", "model": model}

    monkeypatch.setattr(kllm_service, "set_keep", fake_set_keep)
    monkeypatch.setattr(kllm_service, "unload_model", fake_unload)
    result = await kllm_autoload.manual_unload_model(
        test_db,
        MODEL,
        confirm=True,
        force=False,
        admin_id=uuid.uuid4(),
        disable_always_on=True,
    )
    assert disabled == [0]
    assert result["always_on_disabled"] is True


async def test_default_model_unload_refuses_when_effective_always_on_persists(
    test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)
    monkeypatch.setattr(kllm_service, "get_default_model", _default_model)

    async def fake_config():
        return {
            "reachable": True,
            "size": 1,
            "enabled": True,
            "verified": True,
            "autoscale_min_backends": 1,
            "desired_pool": 0,
        }

    async def fake_set_keep(db, size, *, confirm):
        return {
            "status": "always_on_update_incomplete",
            "size": size,
            "verified": True,
            "effectively_disabled": False,
            "effective_min_backends": 1,
        }

    async def forbidden_unload(*args, **kwargs):
        raise AssertionError("no unload may proceed while always-on is effective")

    monkeypatch.setattr(kllm_service, "get_autoscale_config", fake_config)
    monkeypatch.setattr(kllm_service, "set_keep", fake_set_keep)
    monkeypatch.setattr(kllm_service, "unload_model", forbidden_unload)

    with pytest.raises(KllmConflictError) as exc:
        await kllm_autoload.manual_unload_model(
            test_db,
            MODEL,
            confirm=True,
            force=False,
            admin_id=uuid.uuid4(),
            disable_always_on=True,
        )
    assert exc.value.reason_code == "always_on_effective_not_disabled"


async def test_set_keep_reports_effective_state_after_update(
    test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)

    async def fake_post(path, payload, *, timeout=15.0):
        assert path == "/admin/api/keep"
        assert payload == {"size": 0}
        return {"ok": True}

    async def fake_config():
        return {
            "reachable": True,
            "size": 1,
            "enabled": True,
            "verified": True,
            "autoscale_min_backends": 1,
            "desired_pool": 0,
            "effectively_disabled": False,
        }

    monkeypatch.setattr(kllm_service, "_post_json", fake_post)
    monkeypatch.setattr(kllm_service, "get_autoscale_config", fake_config)

    result = await kllm_service.set_keep(test_db, 0, confirm=False)
    assert result["status"] == "always_on_update_incomplete"
    assert result["desired_pool_size"] == 0
    assert result["effective_min_backends"] == 1
    assert result["effectively_disabled"] is False
    assert result["verified"] is True


async def _default_model(db):
    return MODEL


async def test_model_override_blocks_automatic_loading(test_db, gateway_enabled):
    await _seed_managed_provider(test_db)
    test_db.add(
        ModelOverride(
            provider_slug="kllm",
            model_id=MODEL,
            status="disabled",
            message="maintenance",
        )
    )
    await test_db.commit()
    with pytest.raises(KllmConflictError) as exc:
        await kllm_autoload._assert_load_allowed(test_db, MODEL)
    assert exc.value.reason_code == "admin_disabled"


# ---------------------------------------------------------------------------
# review recovery, cancellation, timeout
# ---------------------------------------------------------------------------


async def test_review_wait_recovers_from_idle_unload_exactly_once(
    test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)
    policy = _policy("review_autoload")
    monkeypatch.setattr(kllm_autoload, "get_policy", lambda db=None, *, force=True: _policy("review_autoload"))
    monkeypatch.setattr(kllm_autoload, "_POLL_INTERVAL_SECONDS", 0.01)

    # Poll sees loading, then idle-unloaded; the locked re-check still sees
    # unloaded before the load request; then loading; then finally ready.
    statuses = ["loading", "unloaded", "unloaded", "loading", "loaded"]

    async def fake_read(db, model):
        status = statuses.pop(0) if statuses else "loaded"
        return _model(status, ready=status == "loaded")

    monkeypatch.setattr(kllm_autoload, "_read_model", fake_read)
    requested: list[str] = []

    async def fake_request(db, model, current_policy):
        requested.append(model)
        return {"status": "loading", "model": model}

    monkeypatch.setattr(kllm_autoload, "_request_load_once", fake_request)

    result = await kllm_autoload.wait_until_ready(
        test_db, MODEL, timeout=2, allow_recovery=True, policy=policy
    )
    assert result.ready is True
    assert requested == [MODEL]


async def test_review_wait_cancel_after_first_poll(test_db, gateway_enabled, monkeypatch):
    await _seed_managed_provider(test_db)
    policy = _policy("review_autoload")
    monkeypatch.setattr(kllm_autoload, "_POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(kllm_autoload, "_read_model", _read_loading)

    checks = 0

    async def cancelled():
        nonlocal checks
        checks += 1
        return checks > 1

    requested: list[str] = []

    async def fake_request(db, model, current_policy):
        requested.append(model)
        return {"status": "loading", "model": model}

    monkeypatch.setattr(kllm_autoload, "_request_load_once", fake_request)

    with pytest.raises(asyncio.CancelledError):
        await kllm_autoload.wait_until_ready(
            test_db,
            MODEL,
            timeout=2,
            cancel_check=cancelled,
            allow_recovery=True,
            policy=policy,
        )
    assert requested == []


async def _read_loading(db, model):
    return _model("loading")


async def test_review_wait_cancel_after_recovery_request(
    test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)
    policy = _policy("review_autoload")
    monkeypatch.setattr(kllm_autoload, "_POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(kllm_autoload, "_read_model", _read_unloaded)

    requested: list[str] = []

    async def fake_request(db, model, current_policy):
        requested.append(model)
        return {"status": "loading", "model": model}

    monkeypatch.setattr(kllm_autoload, "_request_load_once", fake_request)
    checks = 0

    async def cancel_after_request():
        nonlocal checks
        checks += 1
        return bool(requested) and checks > 1

    with pytest.raises(asyncio.CancelledError):
        await kllm_autoload.wait_until_ready(
            test_db,
            MODEL,
            timeout=2,
            cancel_check=cancel_after_request,
            allow_recovery=True,
            policy=policy,
        )
    assert requested == [MODEL]


async def test_review_wait_timeout_has_safe_reason_code(
    test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)
    monkeypatch.setattr(kllm_autoload, "_POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(kllm_autoload, "_read_model", _read_loading)

    with pytest.raises(KllmUnavailableError) as exc:
        await kllm_autoload.wait_until_ready(test_db, MODEL, timeout=1)
    assert exc.value.reason_code == "load_timeout"


async def test_policy_defaults_include_independent_session_group(test_db):
    policy = await kllm_autoload.get_policy(test_db, force=True)
    assert policy["review_autoload"]["enabled"] is False
    assert policy["login_preload"]["enabled"] is False
    assert policy["active_session_autoload"]["enabled"] is False
    assert policy["active_session_autoload"]["allowed_models"] == []


async def test_manual_blocks_survive_policy_updates(test_db, gateway_enabled):
    await _seed_managed_provider(test_db)
    await kllm_autoload.set_manual_block(test_db, MODEL, admin_id=uuid.uuid4())
    await kllm_autoload.update_policy(
        test_db,
        {"review_autoload": {"enabled": True, "allowed_models": [MODEL]}},
    )
    await test_db.commit()
    assert await kllm_autoload.is_manually_blocked(test_db, MODEL) is True
    assert (
        await test_db.execute(
            select(PlatformSetting).where(
                PlatformSetting.key == kllm_autoload.KLLM_MANUAL_BLOCK_KEY
            )
        )
    ).scalars().first() is not None
