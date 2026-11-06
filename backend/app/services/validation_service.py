import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import encryption_service
from app.models.api_key import ApiKey
from app.services.api_key_service import api_key_service
from app.services.health_monitor import health_monitor
from app.services.model_discovery import (
    model_discovery_engine,
)
from app.services.provider_registry import provider_registry_service

PER_KEY_VALIDATION_TIMEOUT_SECONDS = 22.0

import re

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-./+]{4,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-./+]{4,}"),
    re.compile(r"gsk_[A-Za-z0-9_\-./+]{4,}"),
    re.compile(r"xai-[A-Za-z0-9_\-./+]{4,}"),
    re.compile(r"nvapi-[A-Za-z0-9_\-./+]{4,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-./+=]+", re.IGNORECASE),
    re.compile(r"api[_-]?key\s*[:=]\s*['\"]?[^'\"\s,}]+", re.IGNORECASE),
)


def sanitize_error_message(message: str) -> str:
    cleaned = message or ""
    for pattern in _SECRET_PATTERNS:
        cleaned = pattern.sub("[redacted]", cleaned)
    return cleaned[:300]


_BUSY_ERROR_TYPES = {
    "rate_limited",
    "quota_exceeded",
    "insufficient_credits",
    "no_free_model",
    "provider_unavailable",
    "timeout",
}

_SAFE_MESSAGES = {
    "invalid_key": "Invalid API key.",
    "authentication_error": "Provider authentication failed.",
    "authorization_error": "Provider authorization failed. Check key permissions.",
    "rate_limited": "Rate limit reached. Try again later.",
    "quota_exceeded": "Provider quota reached. Try again later.",
    "insufficient_credits": "The provider key has insufficient credits. Add credits to continue.",
    "no_free_model": "No free model could be verified with this key. The key remains active.",
    "provider_unavailable": "Provider is temporarily unavailable.",
    "timeout": "Validation timed out.",
    "decryption_error": "Stored credential could not be decrypted.",
    "unknown_provider": "Provider is not supported for validation.",
    "configuration_error": "Provider is not configured correctly.",
    "empty_models": "Provider returned no usable models.",
    "internal_error": "Validation encountered an internal error.",
    "no_key": "No enabled API key is available for this provider.",
}


def _classify_exception(exc: BaseException) -> tuple[str, str | None, str]:
    error_type = getattr(exc, "error_type", None)
    if error_type in _SAFE_MESSAGES:
        status_value = "busy" if error_type in _BUSY_ERROR_TYPES else "failed"
        return status_value, error_type, _SAFE_MESSAGES[error_type]

    lowered = str(exc).lower()
    if any(
        k in lowered
        for k in (
            "invalid_api_key",
            "invalid api key",
            "incorrect api key",
            "401",
            "unauthorized",
        )
    ):
        return "failed", "invalid_key", _SAFE_MESSAGES["invalid_key"]
    if any(k in lowered for k in ("403", "forbidden", "permission", "access denied")):
        return "failed", "authorization_error", _SAFE_MESSAGES["authorization_error"]
    if any(k in lowered for k in ("429", "rate_limit", "rate limit", "rate-limit")):
        return "busy", "rate_limited", _SAFE_MESSAGES["rate_limited"]
    if any(
        k in lowered
        for k in (
            "402",
            "payment required",
            "insufficient credit",
            "insufficient_credit",
            "insufficient funds",
            "out of credits",
            "no credits",
        )
    ):
        return "busy", "insufficient_credits", _SAFE_MESSAGES["insufficient_credits"]
    if "quota" in lowered:
        return "busy", "quota_exceeded", _SAFE_MESSAGES["quota_exceeded"]
    if any(
        k in lowered
        for k in (
            "timeout",
            "timed out",
            "deadline exceeded",
            "503",
            "502",
            "504",
            "service_unavailable",
            "service unavailable",
            "temporarily unavailable",
            "connection",
            "network",
            "server error",
            "overloaded",
        )
    ):
        if "timeout" in lowered or "timed out" in lowered or "deadline" in lowered:
            return "busy", "timeout", _SAFE_MESSAGES["timeout"]
        return "busy", "provider_unavailable", _SAFE_MESSAGES["provider_unavailable"]
    return "failed", "provider_unavailable", _SAFE_MESSAGES["provider_unavailable"]


@dataclass
class ValidationOutcome:
    status: str
    error_type: str | None
    message: str
    model: str | None = None
    latency_ms: float | None = None
    checked_at: datetime | None = None


def _accessible_models(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        m
        for m in models
        if m.get("accessible", True) and not m.get("deprecated", False)
    ]


def _select_model(provider: str, models: list[dict[str, Any]]) -> str | None:
    try:
        # Registry lookup is async; callers use select_validation_model for that.
        pass
    except Exception:
        pass
    accessible = _accessible_models(models)
    if not accessible:
        return None
    return accessible[0].get("canonical_model_name") or accessible[0].get("model_name")


async def select_validation_model(
    db: AsyncSession, provider: str, models: list[dict[str, Any]]
) -> str | None:
    accessible = _accessible_models(models)
    if not accessible:
        return None
    try:
        row = await provider_registry_service.get_by_slug(db, provider)
    except Exception:
        row = None
    if row is not None and getattr(row, "default_model", None):
        default_name = row.default_model
        if any(
            (m.get("canonical_model_name") or m.get("model_name")) == default_name
            for m in accessible
        ):
            return default_name
    return accessible[0].get("canonical_model_name") or accessible[0].get("model_name")


async def validate_key_record(
    db: AsyncSession,
    key: ApiKey,
    *,
    force_refresh: bool = True,
    user_id: uuid.UUID | None = None,
) -> ValidationOutcome:
    checked_at = datetime.now(UTC)
    started = datetime.now(UTC)
    try:
        raw_key = encryption_service.decrypt(key.encrypted_key)
    except Exception:
        outcome = ValidationOutcome(
            status="failed",
            error_type="decryption_error",
            message=_SAFE_MESSAGES["decryption_error"],
            checked_at=checked_at,
        )
        key.is_valid = False
        db.add(key)
        await db.commit()
        try:
            await api_key_service.record_health(
                db,
                key.id,
                "unhealthy",
                "decryption_error",
                sanitize_error_message("Stored credential could not be decrypted."),
            )
        except Exception:
            pass
        return outcome

    provider = (key.provider or "").lower()
    litellm_provider = model_discovery_engine.LITELLM_PROVIDER_MAP.get(provider)
    if not litellm_provider:
        outcome = ValidationOutcome(
            status="failed",
            error_type="unknown_provider",
            message=_SAFE_MESSAGES["unknown_provider"],
            checked_at=checked_at,
        )
        key.is_valid = False
        db.add(key)
        await db.commit()
        try:
            await api_key_service.record_health(
                db, key.id, "unhealthy", "unknown_provider", _SAFE_MESSAGES["unknown_provider"]
            )
        except Exception:
            pass
        return outcome

    try:
        models = await asyncio.wait_for(
            model_discovery_engine.get_available_models(
                key.provider, raw_key, force_refresh=force_refresh
            ),
            timeout=PER_KEY_VALIDATION_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        status_value, error_type, safe_message = "busy", "timeout", _SAFE_MESSAGES["timeout"]
    except Exception as exc:
        status_value, error_type, safe_message = _classify_exception(exc)
    else:
        if models:
            status_value, error_type, safe_message = "success", None, f"{len(models)} models accessible"
        else:
            status_value, error_type, safe_message = "failed", "empty_models", _SAFE_MESSAGES["empty_models"]

    latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000.0
    model_name = None
    if status_value == "success" and models:
        model_name = await select_validation_model(db, key.provider, models)

    if status_value == "success":
        key.is_valid = True
        health_status = "healthy"
        health_error_type = None
        health_message = None
        try:
            await api_key_service.record_health(
                db,
                key.id,
                health_status,
                health_error_type,
                health_message,
                latency_ms=latency_ms,
                model_name=model_name,
            )
        except Exception:
            pass
    elif status_value == "busy":
        key.is_valid = key.is_valid
        health_status = "busy"
        health_error_type = error_type
        health_message = sanitize_error_message(safe_message)
        try:
            await api_key_service.record_health(
                db,
                key.id,
                health_status,
                health_error_type,
                health_message,
                latency_ms=latency_ms,
                model_name=model_name,
            )
        except Exception:
            pass
    else:
        key.is_valid = False
        health_status = "unhealthy"
        health_error_type = error_type
        health_message = sanitize_error_message(safe_message)
        try:
            await api_key_service.record_health(
                db,
                key.id,
                health_status,
                health_error_type,
                health_message,
                latency_ms=latency_ms,
                model_name=model_name,
            )
        except Exception:
            pass

    db.add(key)
    await db.commit()
    await db.refresh(key)

    return ValidationOutcome(
        status=status_value,
        error_type=error_type,
        message=safe_message,
        model=model_name,
        latency_ms=latency_ms,
        checked_at=checked_at,
    )


async def check_provider(
    db: AsyncSession,
    user_id: uuid.UUID,
    provider: str,
) -> ValidationOutcome:
    stmt = (
        select(ApiKey)
        .where(ApiKey.user_id == user_id)
        .where(ApiKey.provider.ilike(provider))
        .where(ApiKey.is_enabled.is_(True))
        .order_by(ApiKey.is_valid.desc(), ApiKey.last_used_at.desc().nulls_last())
    )
    result = await db.execute(stmt)
    key = result.scalars().first()
    if key is None:
        return ValidationOutcome(
            status="failed",
            error_type="no_key",
            message=_SAFE_MESSAGES["no_key"],
            checked_at=datetime.now(UTC),
        )

    outcome = await validate_key_record(db, key, force_refresh=True, user_id=user_id)

    if outcome.status == "success":
        await health_monitor.record_success(
            db,
            provider,
            outcome.latency_ms or 0.0,
            model_name=outcome.model,
            user_id=user_id,
        )
    elif outcome.status == "busy":
        await health_monitor.record_failure(
            db,
            provider,
            outcome.error_type or "provider_unavailable",
            outcome.message,
            latency_ms=outcome.latency_ms,
            model_name=outcome.model,
            user_id=user_id,
            auth_failure=False,
        )
    elif outcome.error_type in ("invalid_key", "authentication_error", "authorization_error"):
        await health_monitor.record_failure(
            db,
            provider,
            outcome.error_type,
            outcome.message,
            latency_ms=outcome.latency_ms,
            model_name=outcome.model,
            user_id=user_id,
            auth_failure=True,
        )
    else:
        await health_monitor.record_failure(
            db,
            provider,
            outcome.error_type or "provider_unavailable",
            outcome.message,
            latency_ms=outcome.latency_ms,
            model_name=outcome.model,
            user_id=user_id,
            auth_failure=False,
        )

    return outcome



class ValidationService:
    validate_key_record = staticmethod(validate_key_record)
    check_provider = staticmethod(check_provider)
    select_validation_model = staticmethod(select_validation_model)


validation_service = ValidationService()
