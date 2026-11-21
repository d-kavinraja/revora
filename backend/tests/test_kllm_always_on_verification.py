"""Always-on configuration verification tests (no live kLLM calls)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.services import kllm_autoload, kllm_service
from app.services.kllm_service import (
    KllmConflictError,
    KllmUnavailableError,
)

MODEL = "qwen3.8-27b"


def _fetch(payload):
    async def reader(path, *, timeout):
        assert path == "/admin/api/autoscale/config"
        return payload, None

    return reader


@pytest.fixture(autouse=True)
def _kllm_enabled(monkeypatch):
    monkeypatch.setattr(kllm_service.settings, "KLLM_ENABLED", True, raising=False)


async def test_valid_configuration_is_verified(monkeypatch):
    monkeypatch.setattr(
        kllm_service,
        "_fetch_json",
        _fetch(
            {
                "settings": {"enabled": True, "min_backends": 1},
                "desired_pool": 0,
            }
        ),
    )
    config = await kllm_service.get_autoscale_config()
    assert config["verified"] is True
    assert config["autoscale_min_backends"] == 1
    assert config["desired_pool"] == 0
    assert config["size"] == 1
    assert config["effectively_disabled"] is False


async def test_missing_settings_is_unverified(monkeypatch):
    monkeypatch.setattr(kllm_service, "_fetch_json", _fetch({"desired_pool": 0}))
    config = await kllm_service.get_autoscale_config()
    assert config["verified"] is False
    assert config["size"] is None
    assert config["effectively_disabled"] is None


async def test_missing_min_backends_is_unverified(monkeypatch):
    monkeypatch.setattr(
        kllm_service,
        "_fetch_json",
        _fetch({"settings": {"enabled": True}, "desired_pool": 0}),
    )
    config = await kllm_service.get_autoscale_config()
    assert config["verified"] is False


async def test_missing_desired_pool_is_unverified(monkeypatch):
    monkeypatch.setattr(
        kllm_service,
        "_fetch_json",
        _fetch({"settings": {"min_backends": 0}}),
    )
    config = await kllm_service.get_autoscale_config()
    assert config["verified"] is False


@pytest.mark.parametrize(
    "payload",
    [
        {"settings": {"min_backends": "bad"}, "desired_pool": 0},
        {"settings": {"min_backends": 0}, "desired_pool": "bad"},
        {"settings": {"min_backends": None}, "desired_pool": 0},
        {"settings": {"min_backends": -1}, "desired_pool": 0},
    ],
)
async def test_malformed_numeric_values_are_unverified(monkeypatch, payload):
    monkeypatch.setattr(kllm_service, "_fetch_json", _fetch(payload))
    config = await kllm_service.get_autoscale_config()
    assert config["verified"] is False


async def test_upstream_read_failure_raises(monkeypatch):
    async def failed_reader(path, *, timeout):
        return None, "unreachable"

    monkeypatch.setattr(kllm_service, "_fetch_json", failed_reader)
    with pytest.raises(KllmUnavailableError):
        await kllm_service.get_autoscale_config()


async def test_verified_effective_disablement(monkeypatch):
    monkeypatch.setattr(
        kllm_service,
        "_fetch_json",
        _fetch({"settings": {"min_backends": 0}, "desired_pool": 0}),
    )
    config = await kllm_service.get_autoscale_config()
    assert config["verified"] is True
    assert config["effectively_disabled"] is True
    assert config["size"] == 0


async def test_effective_disablement_blocked_by_positive_min_backends(monkeypatch):
    monkeypatch.setattr(
        kllm_service,
        "_fetch_json",
        _fetch({"settings": {"min_backends": 2}, "desired_pool": 0}),
    )
    config = await kllm_service.get_autoscale_config()
    assert config["verified"] is True
    assert config["effectively_disabled"] is False
    assert config["size"] == 2


async def test_set_keep_does_not_report_verified_success_when_unverified(
    test_db, monkeypatch
):
    async def enabled(db):
        return True

    async def post(path, payload, *, timeout=15.0):
        assert path == "/admin/api/keep"
        return {"ok": True}

    async def unverified():
        return {
            "reachable": True,
            "verified": False,
            "size": None,
            "effectively_disabled": None,
            "desired_pool": None,
            "autoscale_min_backends": None,
        }

    monkeypatch.setattr(kllm_service, "is_enabled", enabled)
    monkeypatch.setattr(kllm_service, "_post_json", post)
    monkeypatch.setattr(kllm_service, "get_autoscale_config", unverified)

    result = await kllm_service.set_keep(test_db, 0, confirm=False)
    assert result["verified"] is False
    assert result["status"] == "always_on_update_unverified"
    assert result["effectively_disabled"] is None


async def test_set_keep_reports_verified_disablement(test_db, monkeypatch):
    async def enabled(db):
        return True

    async def post(path, payload, *, timeout=15.0):
        return {"ok": True}

    async def verified():
        return {
            "reachable": True,
            "verified": True,
            "size": 0,
            "effectively_disabled": True,
            "desired_pool": 0,
            "autoscale_min_backends": 0,
        }

    monkeypatch.setattr(kllm_service, "is_enabled", enabled)
    monkeypatch.setattr(kllm_service, "_post_json", post)
    monkeypatch.setattr(kllm_service, "get_autoscale_config", verified)

    result = await kllm_service.set_keep(test_db, 0, confirm=False)
    assert result["verified"] is True
    assert result["status"] == "always_on_disabled"
    assert result["effectively_disabled"] is True


async def test_unverified_always_on_is_not_projected_as_disabled(
    admin_client, monkeypatch
):
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
            models=[],
            backends=[],
            pending=[],
            summary={},
            clients=[],
            traffic={},
            supervisor=False,
            autoscale=False,
        )

    async def unverified():
        return {
            "reachable": True,
            "verified": False,
            "size": None,
            "effectively_disabled": None,
            "desired_pool": None,
            "autoscale_min_backends": None,
        }

    monkeypatch.setattr(kllm_service, "get_snapshot", fake_snapshot)
    monkeypatch.setattr(kllm_service, "get_autoscale_config", unverified)

    response = admin_client.get("/api/v1/admin/kllm")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["always_on_verified"] is False
    assert body["always_on_size"] is None
    assert body["always_on_min_backends"] is None


async def test_manual_unload_refuses_missing_verification(test_db, monkeypatch):
    async def default_model(db):
        return MODEL

    async def unverified():
        return {
            "reachable": True,
            "verified": False,
            "size": None,
            "effectively_disabled": None,
        }

    async def forbidden(*args, **kwargs):
        raise AssertionError("no unload may proceed when verification is absent")

    monkeypatch.setattr(kllm_service, "get_default_model", default_model)
    monkeypatch.setattr(kllm_service, "get_autoscale_config", unverified)
    monkeypatch.setattr(kllm_service, "unload_model", forbidden)

    with pytest.raises(KllmConflictError) as exc:
        await kllm_autoload.manual_unload_model(
            test_db,
            MODEL,
            confirm=True,
            force=False,
            admin_id=uuid.uuid4(),
            disable_always_on=True,
        )
    assert exc.value.reason_code == "always_on_unverifiable"


async def test_manual_unload_refuses_unverified_effective_state(
    test_db, monkeypatch
):
    async def default_model(db):
        return MODEL

    async def unverified():
        return {
            "reachable": True,
            "verified": False,
            "size": 1,
            "effectively_disabled": None,
        }

    async def forbidden(*args, **kwargs):
        raise AssertionError("no unload may proceed with unverified always-on")

    monkeypatch.setattr(kllm_service, "get_default_model", default_model)
    monkeypatch.setattr(kllm_service, "get_autoscale_config", unverified)
    monkeypatch.setattr(kllm_service, "unload_model", forbidden)

    with pytest.raises(KllmConflictError) as exc:
        await kllm_autoload.manual_unload_model(
            test_db,
            MODEL,
            confirm=True,
            force=False,
            admin_id=uuid.uuid4(),
            disable_always_on=True,
        )
    assert exc.value.reason_code == "always_on_unverifiable"


async def test_manual_unload_existing_verified_flow(test_db, monkeypatch):
    async def default_model(db):
        return MODEL

    async def verified_config():
        return {
            "reachable": True,
            "verified": True,
            "size": 2,
            "effectively_disabled": False,
            "desired_pool": 0,
            "autoscale_min_backends": 2,
        }

    async def fake_set_keep(db, size, *, confirm):
        return {
            "status": "always_on_disabled",
            "size": size,
            "verified": True,
            "effectively_disabled": True,
            "effective_min_backends": 0,
        }

    async def fake_unload(db, model, *, confirm, force):
        return {"status": "success", "model": model}

    monkeypatch.setattr(kllm_service, "get_default_model", default_model)
    monkeypatch.setattr(kllm_service, "get_autoscale_config", verified_config)
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
    assert result["always_on_disabled"] is True
