"""Installation authentication lifecycle helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.github.errors import bounded_backoff
from app.models.github import Installation

ACTIVE = "active"
SUSPENDED = "suspended"
INACCESSIBLE = "inaccessible"
REAUTHORIZATION_REQUIRED = "reauthorization_required"
CONFIGURATION_ERROR = "configuration_error"


def _now(now: datetime | None = None) -> datetime:
    return now or datetime.now(UTC)


def _configured_app_id() -> str | None:
    return settings.GITHUB_APP_ID


def app_id_matches(installation: Installation) -> bool:
    configured = _configured_app_id()
    if configured is None or installation.app_id is None:
        return True
    return str(installation.app_id) == str(configured)


def can_attempt_token(installation: Installation, now: datetime | None = None) -> bool:
    now = _now(now)
    if installation.suspended_at is not None:
        return False
    if not installation.permissions_ok:
        return False
    if installation.lifecycle_status != ACTIVE:
        return False
    if installation.retry_after is not None and installation.retry_after > now:
        return False
    return app_id_matches(installation)


def metadata_recheck_due(installation: Installation, now: datetime | None = None) -> bool:
    now = _now(now)
    if not app_id_matches(installation):
        return False
    return not (installation.retry_after is not None and installation.retry_after > now)


def record_auth_success(
    installation: Installation,
    *,
    app_id: int | str | None = None,
    now: datetime | None = None,
) -> None:
    now = _now(now)
    if app_id is not None:
        installation.app_id = int(app_id)
    installation.lifecycle_status = ACTIVE
    installation.suspended_at = None
    installation.last_auth_checked_at = now
    installation.last_auth_success_at = now
    installation.last_auth_error_category = None
    installation.auth_failure_count = 0
    installation.retry_after = None


def _backoff_for(category: str, failure_count: int, explicit_retry_after: datetime | None, now: datetime) -> datetime:
    if explicit_retry_after is not None and explicit_retry_after > now:
        return explicit_retry_after

    if category == "suspended":
        return now + timedelta(hours=24)
    if category == "inaccessible":
        return now + timedelta(hours=24)
    if category == "reauthorization_required":
        return bounded_backoff(failure_count, base_seconds=15 * 60, max_seconds=24 * 60 * 60, now=now)
    if category == "configuration_error":
        return bounded_backoff(failure_count, base_seconds=5 * 60, max_seconds=60 * 60, now=now)
    if category == "rate_limited":
        return bounded_backoff(failure_count, base_seconds=60, max_seconds=60 * 60, now=now)
    if category == "transient_not_found":
        return bounded_backoff(failure_count, base_seconds=60, max_seconds=60 * 60, now=now)
    return bounded_backoff(failure_count, base_seconds=60, max_seconds=60 * 60, now=now)


def record_auth_failure(
    installation: Installation,
    category: str,
    *,
    status_code: int | None = None,
    retry_after: datetime | None = None,
    now: datetime | None = None,
    suspended: bool = False,
) -> None:
    now = _now(now)
    installation.auth_failure_count = (installation.auth_failure_count or 0) + 1
    installation.last_auth_checked_at = now
    installation.last_auth_error_category = category

    if category == "suspended" or suspended:
        installation.lifecycle_status = SUSPENDED
        installation.suspended_at = installation.suspended_at or now
        installation.permissions_ok = False
    elif category == "inaccessible":
        installation.lifecycle_status = INACCESSIBLE
    elif category == "reauthorization_required":
        installation.lifecycle_status = REAUTHORIZATION_REQUIRED
    elif category == "configuration_error":
        installation.lifecycle_status = CONFIGURATION_ERROR
    else:
        installation.lifecycle_status = ACTIVE

    installation.retry_after = _backoff_for(category, installation.auth_failure_count, retry_after, now)


def mark_suspended(installation: Installation, *, now: datetime | None = None) -> None:
    record_auth_failure(installation, SUSPENDED, now=now, suspended=True)


def mark_inaccessible(installation: Installation, *, now: datetime | None = None) -> None:
    record_auth_failure(installation, INACCESSIBLE, now=now)


def mark_reauthorization_required(installation: Installation, *, now: datetime | None = None) -> None:
    record_auth_failure(installation, REAUTHORIZATION_REQUIRED, now=now)


def mark_configuration_error(installation: Installation, *, now: datetime | None = None) -> None:
    record_auth_failure(installation, CONFIGURATION_ERROR, now=now)


def clear_auth_state(installation: Installation, *, now: datetime | None = None) -> None:
    now = _now(now)
    installation.lifecycle_status = ACTIVE
    installation.last_auth_error_category = None
    installation.auth_failure_count = 0
    installation.retry_after = None
    installation.last_auth_checked_at = now
    installation.last_auth_success_at = now
