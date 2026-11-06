from datetime import UTC, datetime, timedelta

from app.models.github import Installation
from app.services.installation_lifecycle import (
    ACTIVE,
    CONFIGURATION_ERROR,
    INACCESSIBLE,
    REAUTHORIZATION_REQUIRED,
    SUSPENDED,
    can_attempt_token,
    metadata_recheck_due,
    record_auth_failure,
    record_auth_success,
)


def _inst(**overrides):
    base = {
        "installation_id": 1,
        "account_id": 1,
        "account_login": "org",
        "account_type": "Organization",
        "user_id": uuid.uuid4() if False else None,
        "repository_selection": "all",
        "permissions": {},
        "events": {},
        "suspended_at": None,
        "permissions_ok": True,
        "lifecycle_status": ACTIVE,
        "auth_failure_count": 0,
        "retry_after": None,
        "app_id": None,
    }
    base.update(overrides)
    return Installation(**base)


import uuid


def test_active_installation_can_attempt_token():
    inst = _inst()
    assert can_attempt_token(inst) is True


def test_suspended_installation_cannot_attempt_token():
    inst = _inst(lifecycle_status=SUSPENDED, suspended_at=datetime.now(UTC))
    assert can_attempt_token(inst) is False


def test_inaccessible_installation_cannot_attempt_token():
    inst = _inst(lifecycle_status=INACCESSIBLE)
    assert can_attempt_token(inst) is False


def test_reauthorization_required_cannot_attempt_token():
    inst = _inst(lifecycle_status=REAUTHORIZATION_REQUIRED, permissions_ok=False)
    assert can_attempt_token(inst) is False


def test_configuration_error_cannot_attempt_token():
    inst = _inst(lifecycle_status=CONFIGURATION_ERROR)
    assert can_attempt_token(inst) is False


def test_future_retry_after_blocks_token():
    inst = _inst(retry_after=datetime.now(UTC) + timedelta(hours=1))
    assert can_attempt_token(inst) is False


def test_due_metadata_recheck():
    inst = _inst(lifecycle_status=INACCESSIBLE, retry_after=datetime.now(UTC) - timedelta(minutes=1))
    assert metadata_recheck_due(inst) is True
    inst2 = _inst(lifecycle_status=INACCESSIBLE, retry_after=datetime.now(UTC) + timedelta(hours=1))
    assert metadata_recheck_due(inst2) is False


def test_record_auth_failure_sets_state_and_backoff():
    inst = _inst()
    record_auth_failure(inst, INACCESSIBLE)
    assert inst.lifecycle_status == INACCESSIBLE
    assert inst.last_auth_error_category == INACCESSIBLE
    assert inst.auth_failure_count == 1
    assert inst.retry_after is not None


def test_record_auth_success_clears_state():
    inst = _inst(lifecycle_status=INACCESSIBLE, auth_failure_count=3, retry_after=datetime.now(UTC) + timedelta(hours=1))
    record_auth_success(inst, app_id=42)
    assert inst.lifecycle_status == ACTIVE
    assert inst.app_id == 42
    assert inst.auth_failure_count == 0
    assert inst.retry_after is None
    assert inst.last_auth_error_category is None
