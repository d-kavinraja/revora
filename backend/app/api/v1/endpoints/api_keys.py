import asyncio
import logging
import re
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.deps_flags import require_feature
from app.core.security import encryption_service
from app.db.session import get_db
from app.models.github import Installation, Repository
from app.models.user import User
from app.schemas.api_key import ApiKey as ApiKeySchema
from app.schemas.api_key import ApiKeyCreate, ApiKeyUpdate
from app.schemas.operation import OperationJobRead
from app.schemas.usage import (
    ApiKeyHealthRead,
    ApiKeyRotate,
    BulkValidateResult,
    BulkValidationSummary,
    PerKeyValidationResult,
)
from app.services.api_key_service import api_key_service
from app.services.provider_registry import provider_registry_service

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
    re.compile(r"gsk_[A-Za-z0-9_\-./+]{4,}"),
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
        # Exhausted balance (notably OpenRouter 402): busy-preserving, never
        # invalid — the key itself is fine, it just cannot pay right now.
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
    _: None = Depends(require_feature("api_keys_add")),
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
        "ollama_cloud",
        "cohere",
        "mistral",
        "nvidia",
    ]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid LLM provider",
        )

    # Phase 4 key-addition policy (§10): blocked providers and providers
    # with `allow_key_addition=false` reject NEW credentials. Existing
    # keys for the same provider remain stored, listed and rotatable (D9).
    # A provider missing from the registry keeps its legacy behavior.
    _, provider_row = await provider_registry_service.usability(db, provider)
    if provider_row is not None:
        blocked = (
            not provider_row.is_enabled
            or provider_row.status in ("disabled", "unavailable", "coming_soon")
            or not provider_row.allow_key_addition
        )
        if blocked:
            detail = provider_row.status_message or (
                f"Adding new keys for provider '{provider}' is currently disabled."
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=detail,
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

    if provider == "groq" and not key_in.api_key.startswith("gsk_"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Groq keys must start with gsk_",
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
    _: None = Depends(require_feature("api_keys_add")),
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

        if provider == "groq" and not key_in.api_key.startswith("gsk_"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Groq keys must start with gsk_",
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


@router.post(
    "/{key_id}/test",
    response_model=OperationJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def test_api_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Enqueue a durable API key connectivity test."""
    db_key = await api_key_service.get_by_id(db, key_id)
    if not db_key or db_key.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found or not owned by user",
        )
    from app.services.operation_service import operation_service

    job, _ = await operation_service.enqueue_api_key_test(db, current_user, key_id)
    return job


@router.post("/{key_id}/rotate", response_model=ApiKeySchema)
async def rotate_api_key(
    key_id: uuid.UUID,
    data: ApiKeyRotate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_feature("api_keys_add")),
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


async def _owner_set_key_enabled(
    db: AsyncSession, key_id: uuid.UUID, user: User, enabled: bool
) -> ApiKeySchema:
    db_key = await api_key_service.get_by_id(db, key_id)
    if not db_key or db_key.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found or not owned by user",
        )
    db_key = await api_key_service.set_enabled(db, db_key, enabled)
    return ApiKeySchema.from_orm_with_mask(db_key, "***")


@router.post("/{key_id}/disable", response_model=ApiKeySchema)
async def disable_api_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Owner switch (phase 4): exclude this credential from all selection
    paths without deleting or decrypting it. Existing key material is
    untouched; re-enable restores eligibility automatically."""
    return await _owner_set_key_enabled(db, key_id, current_user, False)


@router.post("/{key_id}/enable", response_model=ApiKeySchema)
async def enable_api_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Owner switch (phase 4): re-include a previously disabled credential."""
    return await _owner_set_key_enabled(db, key_id, current_user, True)


@router.post(
    "/validate-all",
    response_model=OperationJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def validate_all_keys(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Enqueue durable validation for all of the current user's API keys."""
    from app.services.operation_service import operation_service

    job, _ = await operation_service.enqueue_validate_all(db, current_user)
    return job


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
