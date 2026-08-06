import logging
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
from app.schemas.usage import ApiKeyHealthRead, ApiKeyRotate, BulkValidateResult
from app.services.api_key_service import api_key_service

logger = logging.getLogger(__name__)

router = APIRouter()


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
        "ollama",
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

    from app.services.model_discovery import model_discovery_engine

    background_tasks.add_task(
        model_discovery_engine.get_available_models, provider, key_in.api_key
    )

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
            "ollama",
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
        from app.services.model_discovery import model_discovery_engine

        background_tasks.add_task(
            model_discovery_engine.get_available_models, db_key.provider, raw_key
        )

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
        "ollama": "ollama",
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
        from app.services.model_discovery import model_discovery_engine

        models = await model_discovery_engine.get_available_models(
            db_key.provider, raw_key
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
        err_str = str(e).lower()
        any(
            k in err_str
            for k in [
                "invalid_api_key",
                "invalid api key",
                "401",
                "403",
                "permission",
                "unauthorized",
                "forbidden",
            ]
        )
        is_busy = any(
            k in err_str
            for k in [
                "429",
                "rate_limit",
                "rate limit",
                "quota",
                "503",
                "service_unavailable",
                "temporarily unavailable",
            ]
        )

        if is_busy:
            db_key.is_valid = True
            db.add(db_key)
            await db.commit()
            await api_key_service.record_health(db, db_key.id, "healthy")
            return {
                "status": "success",
                "message": "Key is authenticated but the provider is currently rate-limited or busy.",
            }

        db_key.is_valid = False
        db.add(db_key)
        await db.commit()
        await api_key_service.record_health(
            db, db_key.id, "unhealthy", "auth_error", str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Connectivity test failed: {e}",
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


@router.post("/validate-all")
async def validate_all_keys(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Validate all API keys for the current user."""
    keys = await api_key_service.get_all_for_user(db, current_user.id)
    results = {}

    for key in keys:
        try:
            raw_key = encryption_service.decrypt(key.encrypted_key)
            from app.services.model_discovery import model_discovery_engine

            models = await model_discovery_engine.get_available_models(
                key.provider, raw_key
            )
            if models:
                key.is_valid = True
                await api_key_service.record_health(db, key.id, "healthy")
                results[str(key.id)] = {
                    "status": "success",
                    "message": f"{len(models)} models accessible",
                }
            else:
                key.is_valid = False
                await api_key_service.record_health(
                    db, key.id, "unhealthy", "empty_models", "No models returned"
                )
                results[str(key.id)] = {
                    "status": "failed",
                    "message": "No models returned",
                }
        except Exception as e:
            key.is_valid = False
            await api_key_service.record_health(
                db, key.id, "unhealthy", "error", str(e)
            )
            results[str(key.id)] = {"status": "failed", "message": str(e)}

        db.add(key)
    await db.commit()

    return BulkValidateResult(results=results)


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
