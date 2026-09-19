import asyncio
import logging
import re
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.security import encryption_service
from app.db.session import get_db
from app.models.github import Installation, Repository
from app.models.user import User
from app.schemas.api_key import ApiKey as ApiKeySchema
from app.schemas.api_key import ApiKeyCreate, ApiKeyUpdate
from app.schemas.usage import (
    ApiKeyHealthRead,
    ApiKeyRotate,
    BulkValidateResult,
    BulkValidationSummary,
    PerKeyValidationResult,
)
from app.services.api_key_service import api_key_service

logger = logging.getLogger(__name__)

router = APIRouter()

# Bounded per-key validation budget for bulk validation. Each credential may
# trigger a provider model-list fetch (httpx 10s) plus N concurrent 5s quota
# smoke tests; 22s keeps realistic multi-key runs inside the frontend's bulk
# timeout while preventing one hanging provider from stalling the batch.
PER_KEY_VALIDATION_TIMEOUT_SECONDS = 22.0

# Substrings that must never reach the browser or health records.
_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-./+]{4,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-./+]{4,}"),
    re.compile(r"xai-[A-Za-z0-9_\-./+]{4,}"),
    re.compile(r"nvapi-[A-Za-z0-9_\-./+]{4,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-./+=]+", re.IGNORECASE),
    re.compile(r"api[_-]?key\s*[:=]\s*['\"]?[^'\"\s,}]+", re.IGNORECASE),
)


def sanitize_error_message(message: str) -> str:
    """Strip anything resembling credentials/tokens from an error message."""
    cleaned = message or ""
    for pattern in _SECRET_PATTERNS:
        cleaned = pattern.sub("[redacted]", cleaned)
    # Bound length so provider stack traces cannot flood responses/records.
    return cleaned[:300]


_BUSY_ERROR_TYPES = {
    "rate_limited",
    "quota_exceeded",
    "provider_unavailable",
    "timeout",
}

_SAFE_MESSAGES = {
    "invalid_key": "Invalid API key.",
    "authentication_error": "Provider authentication failed.",
    "authorization_error": "Provider authorization failed. Check key permissions.",
    "rate_limited": "Rate limit reached. Try again later.",
    "quota_exceeded": "Provider quota reached. Try again later.",
    "provider_unavailable": "Provider is temporarily unavailable.",
    "timeout": "Validation timed out.",
    "decryption_error": "Stored credential could not be decrypted.",
    "unknown_provider": "Provider is not supported for validation.",
    "configuration_error": "Provider is not configured correctly.",
    "empty_models": "Provider returned no usable models.",
    "internal_error": "Validation encountered an internal error.",
}


def _classify_exception(exc: BaseException) -> tuple[str, str | None, str]:
    """Map any validation exception to (status, error_type, safe_message).

    Typed discovery errors carry their own error_type. Legacy generic
    exceptions (e.g. from mocks or litellm passthrough) are classified by
    keyword so individual-test and bulk-test stay consistent.
    """
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


@router.get("", response_model=list[ApiKeySchema])
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all API keys for the current user with masked values."""
    db_keys = await api_key_service.get_all_for_user(db, current_user.id)
    results = []
    for key in db_keys:
        try:
            raw_key = encryption_service.decrypt(key.encrypted_key)
        except Exception:
            raw_key = "***"
        results.append(ApiKeySchema.from_orm_with_mask(key, raw_key))
    return results


@router.post("", response_model=ApiKeySchema, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    key_in: ApiKeyCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a new encrypted API key for the current user."""
    provider = key_in.provider.lower()
    if provider not in [
        "openai",
        "anthropic",
        "gemini",
        "groq",
        "deepseek",
        "grok",
        "openrouter",
        "azure_openai",
        "ollama_cloud",
        "cohere",
        "mistral",
        "nvidia",
    ]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid LLM provider",
        )

    if provider == "openai" and not key_in.api_key.startswith("sk-"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="OpenAI keys must start with sk-",
        )

    if provider == "anthropic" and not key_in.api_key.startswith("sk-ant-"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Anthropic keys must start with sk-ant-",
        )

    if provider == "grok" and not key_in.api_key.startswith("xai-"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Grok keys must start with xai-",
        )

    if provider == "nvidia" and not key_in.api_key.startswith("nvapi-"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="NVIDIA NIM keys must start with nvapi-",
        )

    if len(key_in.api_key) < 15:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="API Key is too short",
        )

    db_key = await api_key_service.create(db, current_user.id, key_in)

    from app.services.model_discovery import warm_model_cache

    background_tasks.add_task(warm_model_cache, provider, key_in.api_key)

    return ApiKeySchema.from_orm_with_mask(db_key, key_in.api_key)


@router.put("/{key_id}", response_model=ApiKeySchema)
async def update_api_key(
    key_id: uuid.UUID,
    key_in: ApiKeyUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an API key configuration."""
    db_key = await api_key_service.get_by_id(db, key_id)
    if not db_key or db_key.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found or not owned by user",
        )

    if key_in.api_key:
        provider = db_key.provider.lower()
        if provider not in [
            "openai",
            "anthropic",
            "gemini",
            "groq",
            "deepseek",
            "grok",
            "openrouter",
            "azure_openai",
            "ollama_cloud",
            "cohere",
            "mistral",
            "nvidia",
        ]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid LLM provider",
            )

        if provider == "openai" and not key_in.api_key.startswith("sk-"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="OpenAI keys must start with sk-",
            )

        if provider == "anthropic" and not key_in.api_key.startswith("sk-ant-"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Anthropic keys must start with sk-ant-",
            )

        if provider == "grok" and not key_in.api_key.startswith("xai-"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Grok keys must start with xai-",
            )

        if provider == "nvidia" and not key_in.api_key.startswith("nvapi-"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="NVIDIA NIM keys must start with nvapi-",
            )

        if len(key_in.api_key) < 15:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="API Key is too short",
            )

    db_key = await api_key_service.update(db, db_key, key_in)

    if key_in.api_key:
        raw_key = key_in.api_key
    else:
        try:
            raw_key = encryption_service.decrypt(db_key.encrypted_key)
        except Exception:
            raw_key = "***"

    if raw_key != "***":
        from app.services.model_discovery import warm_model_cache

        background_tasks.add_task(warm_model_cache, db_key.provider, raw_key)

    return ApiKeySchema.from_orm_with_mask(db_key, raw_key)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an API key and clean up repo mappings."""
    db_key = await api_key_service.get_by_id(db, key_id)
    if not db_key or db_key.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found or not owned by user",
        )
    await api_key_service.delete(db, db_key)

    # Clean up repository mappings that reference the deleted key
    key_id_str = str(key_id)
    try:
        inst_result = await db.execute(
            select(Installation).where(Installation.user_id == current_user.id)
        )
        installations = inst_result.scalars().all()
        for inst in installations:
            repo_result = await db.execute(
                select(Repository).where(Repository.installation_id == inst.id)
            )
            repos = repo_result.scalars().all()
            for repo in repos:
                if repo.settings and repo.settings.get("assigned_key_id") == key_id_str:
                    new_settings = dict(repo.settings)
                    new_settings.pop("assigned_provider", None)
                    new_settings.pop("assigned_model", None)
                    new_settings.pop("assigned_key_id", None)
                    repo.settings = new_settings
                    db.add(repo)
        await db.commit()
        logger.info(f"Cleaned up repo mappings for deleted key {key_id_str}")
    except Exception as e:
        logger.error(f"Failed to clean up repo mappings for key {key_id_str}: {e}")


@router.post("/{key_id}/test", response_model=dict[str, Any])
async def test_api_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Test connection with the API key provider."""
    db_key = await api_key_service.get_by_id(db, key_id)
    if not db_key or db_key.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found or not owned by user",
        )

    try:
        raw_key = encryption_service.decrypt(db_key.encrypted_key)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to decrypt stored key: {e}",
        )

    litellm_provider_map = {
        "gemini": "gemini",
        "openai": "openai",
        "anthropic": "anthropic",
        "groq": "groq",
        "deepseek": "deepseek",
        "grok": "xai",
        "openrouter": "openrouter",
        "azure_openai": "azure",
        "ollama_cloud": "openai",
        "cohere": "cohere",
        "mistral": "mistral",
        "nvidia": "nvidia_nim",
    }

    provider = db_key.provider.lower()
    litellm_prov = litellm_provider_map.get(provider)
    if not litellm_prov:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported provider for testing: {db_key.provider}",
        )

    try:
        from app.services.model_discovery import (
            ProviderBusyError,
            model_discovery_engine,
        )

        try:
            models = await asyncio.wait_for(
                model_discovery_engine.get_available_models(
                    db_key.provider, raw_key
                ),
                timeout=PER_KEY_VALIDATION_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            raise ProviderBusyError(
                "Validation timed out.", error_type="timeout"
            )

        if not models:
            raise ValueError(
                "Provider returned an empty model list. The key may be invalid."
            )

        db_key.is_valid = True
        db.add(db_key)
        await db.commit()

        await api_key_service.record_health(db, db_key.id, "healthy")

        return {
            "status": "success",
            "message": f"Key verified — {len(models)} model(s) accessible and quota verified.",
        }

    except Exception as e:
        from app.services.model_discovery import ProviderBusyError as _Busy

        status_value, error_type, safe_message = _classify_exception(e)
        if isinstance(e, _Busy) or status_value == "busy":
            # Busy/transient: the credential may be valid but the provider
            # cannot currently confirm it — preserve validity, do not
            # misreport as invalid.
            db.add(db_key)
            await db.commit()
            await api_key_service.record_health(db, db_key.id, "healthy")
            return {
                "status": "success",
                "message": f"{safe_message} Key remains marked valid.",
            }

        db_key.is_valid = False
        db.add(db_key)
        await db.commit()
        await api_key_service.record_health(
            db, db_key.id, "unhealthy", error_type, sanitize_error_message(str(e))
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Connectivity test failed: {safe_message}",
        )


@router.post("/{key_id}/rotate", response_model=ApiKeySchema)
async def rotate_api_key(
    key_id: uuid.UUID,
    data: ApiKeyRotate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Atomically rotate an API key."""
    db_key = await api_key_service.get_by_id(db, key_id)
    if not db_key or db_key.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found or not owned by user",
        )

    if len(data.api_key) < 15:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="API Key is too short",
        )

    rotated = await api_key_service.rotate(db, key_id, data.api_key)
    return ApiKeySchema.from_orm_with_mask(rotated, data.api_key)


@router.post("/validate-all", response_model=BulkValidateResult)
async def validate_all_keys(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Validate all API keys for the current user.

    Sequential per-key validation with a bounded per-key timeout. One
    credential failure never terminates validation of the remaining
    credentials. Always returns 200 with per-key success/failed/busy
    outcomes plus a summary (request-level auth/DB failures excepted).
    """
    from app.services.model_discovery import (
        ProviderConfigError,
        model_discovery_engine,
    )

    keys = await api_key_service.get_all_for_user(db, current_user.id)
    results: dict[str, PerKeyValidationResult] = {}
    succeeded = failed = busy = 0

    for key in keys:
        key_id = str(key.id)
        previous_valid = key.is_valid
        try:
            try:
                raw_key = encryption_service.decrypt(key.encrypted_key)
            except Exception as e:
                logger.warning(
                    "Bulk validation decryption failed for key %s: %s",
                    key_id,
                    type(e).__name__,
                )
                raise ProviderConfigError(
                    "Stored credential could not be decrypted.",
                    error_type="decryption_error",
                )

            if not model_discovery_engine.LITELLM_PROVIDER_MAP.get(
                (key.provider or "").lower()
            ):
                raise ProviderConfigError(
                    "Provider is not supported for validation.",
                    error_type="unknown_provider",
                )

            try:
                models = await asyncio.wait_for(
                    model_discovery_engine.get_available_models(
                        key.provider, raw_key, force_refresh=True
                    ),
                    timeout=PER_KEY_VALIDATION_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                status_value, error_type, safe_message = (
                    "busy",
                    "timeout",
                    _SAFE_MESSAGES["timeout"],
                )
            else:
                if models:
                    status_value, error_type, safe_message = (
                        "success",
                        None,
                        f"{len(models)} models accessible",
                    )
                else:  # pragma: no cover - discovery raises instead of []
                    status_value, error_type, safe_message = (
                        "failed",
                        "empty_models",
                        _SAFE_MESSAGES["empty_models"],
                    )
        except Exception as e:
            # TimeoutError from wait_for is handled above; anything else is
            # classified here. asyncio.TimeoutError subclasses TimeoutError,
            # so guard explicitly for cancellations converted elsewhere.
            if isinstance(e, TimeoutError):
                status_value, error_type, safe_message = (
                    "busy",
                    "timeout",
                    _SAFE_MESSAGES["timeout"],
                )
            else:
                status_value, error_type, safe_message = _classify_exception(e)
                # _classify_exception never returns success; timeouts raised
                # as ProviderBusyError map to busy with preserved validity.

        if status_value == "success":
            key.is_valid = True
            health_status = "healthy"
            health_error_type = None
            health_message = None
            succeeded += 1
        elif status_value == "busy":
            # Preserve previous validity: transient conditions must not
            # misreport a credential as invalid (nor as verified valid).
            key.is_valid = previous_valid
            health_status = "busy"
            health_error_type = error_type
            health_message = sanitize_error_message(safe_message)
            busy += 1
        else:
            key.is_valid = False
            health_status = "unhealthy"
            health_error_type = error_type
            health_message = sanitize_error_message(safe_message)
            failed += 1

        # Per-key persistence isolated in its own try: a DB failure for one
        # credential must not abort validation of the rest. record_health()
        # commits, so each iteration persists its own key flag + health row
        # atomically (same pattern as the individual test endpoint). No
        # explicit rollback here: the session is request-scoped and a failed
        # iteration is simply logged while collected results are still
        # returned with 200.
        try:
            db.add(key)
            await api_key_service.record_health(
                db, key.id, health_status, health_error_type, health_message
            )
        except Exception as e:
            logger.error(
                "Bulk validation persistence failed for key %s: %s",
                key_id,
                type(e).__name__,
            )
            db.add(key)

        results[key_id] = PerKeyValidationResult(
            status=status_value, message=safe_message, error_type=error_type
        )

    # Best-effort final commit for any remaining in-memory state. If it
    # fails, still return the collected partial results (200) rather than
    # converting everything to a 500 — per-key commits above already
    # persisted what they could.
    try:
        await db.commit()
    except Exception as e:
        logger.error("Bulk validation final commit failed: %s", type(e).__name__)

    return BulkValidateResult(
        results=results,
        summary=BulkValidationSummary(
            total=len(keys), succeeded=succeeded, failed=failed, busy=busy
        ),
    )


@router.get("/{key_id}/health", response_model=list[ApiKeyHealthRead])
async def get_key_health(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get health history for an API key."""
    db_key = await api_key_service.get_by_id(db, key_id)
    if not db_key or db_key.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found or not owned by user",
        )
    return await api_key_service.get_health_history(db, key_id)
