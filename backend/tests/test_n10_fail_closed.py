"""N10 — permission and app-id checks fail closed."""
import uuid

from app.core.config import settings
from app.github.webhooks import _app_id_allowed
from app.services.installation_lifecycle import app_id_matches
from app.services.sync_engine import _has_required_permissions
from app.models.github import Installation

FULL_PERMISSIONS = {
    "pull_requests": "write",
    "checks": "write",
    "contents": "read",
}


def _make_installation(**overrides) -> Installation:
    values = {
        "id": uuid.uuid4(),
        "installation_id": 770001,
        "account_id": 66001,
        "account_login": "fail-closed-acct",
        "account_type": "User",
        "user_id": uuid.uuid4(),
        "repository_selection": "all",
        "permissions": FULL_PERMISSIONS,
        "events": {},
        "permissions_ok": True,
        "lifecycle_status": "active",
        "suspended_at": None,
        "app_id": 12345,
    }
    values.update(overrides)
    return Installation(**values)


def test_empty_permissions_fail_closed():
    assert _has_required_permissions({}, None) is False
    assert _has_required_permissions(None, None) is False


def test_full_permissions_pass():
    assert _has_required_permissions(FULL_PERMISSIONS, None) is True


def test_insufficient_permissions_fail_closed():
    assert (
        _has_required_permissions(
            {"pull_requests": "read", "checks": "write", "contents": "read"}, None
        )
        is False
    )


def test_suspended_fail_closed_even_with_full_permissions():
    assert _has_required_permissions(FULL_PERMISSIONS, object()) is False


def test_app_id_allowed_fails_closed_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_APP_ID", None, raising=False)
    payload = {"installation": {"id": 1, "app_id": 12345}}
    assert _app_id_allowed(payload) is False


def test_app_id_allowed_fails_closed_without_payload_app_id(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_APP_ID", "12345", raising=False)
    assert _app_id_allowed({"installation": {"id": 1}}) is False
    assert _app_id_allowed({}) is False


def test_app_id_allowed_fails_closed_on_mismatch(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_APP_ID", "12345", raising=False)
    payload = {"installation": {"id": 1, "app_id": 99999}}
    assert _app_id_allowed(payload) is False


def test_app_id_allowed_accepts_matching_app(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_APP_ID", "12345", raising=False)
    payload = {"installation": {"id": 1, "app_id": 12345}}
    assert _app_id_allowed(payload) is True


def test_app_id_matches_unconfigured_deployment_fails_open_to_configured(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_APP_ID", None, raising=False)
    assert app_id_matches(_make_installation(app_id=None)) is True


def test_app_id_matches_configured_with_legacy_row_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_APP_ID", "12345", raising=False)
    assert app_id_matches(_make_installation(app_id=None)) is False


def test_app_id_matches_configured_compares_as_strings(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_APP_ID", "12345", raising=False)
    assert app_id_matches(_make_installation(app_id=12345)) is True
    assert app_id_matches(_make_installation(app_id=12346)) is False
