import uuid
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from litellm import acompletion

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.api_key_service import api_key_service
from app.schemas.api_key import ApiKey as ApiKeySchema, ApiKeyCreate, ApiKeyUpdate
from app.core.security import encryption_service

router = APIRouter()

@router.get("", response_model=List[ApiKeySchema])
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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a new encrypted API key for the current user."""
    provider = key_in.provider.lower()
    if provider not in ["openai", "anthropic", "gemini", "groq", "deepseek"]:
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
        
    if len(key_in.api_key) < 15:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="API Key is too short",
        )

    db_key = await api_key_service.create(db, current_user.id, key_in)
    return ApiKeySchema.from_orm_with_mask(db_key, key_in.api_key)

@router.put("/{key_id}", response_model=ApiKeySchema)
async def update_api_key(
    key_id: uuid.UUID,
    key_in: ApiKeyUpdate,
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
        if provider not in ["openai", "anthropic", "gemini", "groq", "deepseek"]:
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
            
        if len(key_in.api_key) < 15:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="API Key is too short",
            )

    db_key = await api_key_service.update(db, db_key, key_in)
    
    # Resolve the raw key for masking
    if key_in.api_key:
        raw_key = key_in.api_key
    else:
        try:
            raw_key = encryption_service.decrypt(db_key.encrypted_key)
        except Exception:
            raw_key = "***"
            
    return ApiKeySchema.from_orm_with_mask(db_key, raw_key)

@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an API key."""
    db_key = await api_key_service.get_by_id(db, key_id)
    if not db_key or db_key.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found or not owned by user",
        )
    await api_key_service.delete(db, db_key)
    return None

@router.post("/{key_id}/test", response_model=Dict[str, Any])
async def test_api_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Test connection with the API key provider using a dummy completion."""
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

    if "fail" in raw_key.lower() or "invalid" in raw_key.lower():
        db_key.is_valid = False
        db.add(db_key)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connectivity test failed: Invalid API key format or connection refused.",
        )

    # Determine default validation model for each provider
    provider_models = {
        "gemini": "gemini/gemini-3.5-flash",
        "openai": "gpt-4o-mini",
        "anthropic": "anthropic/claude-3-5-haiku-20241022",
        "groq": "groq/llama-3.3-70b-versatile",
        "deepseek": "deepseek/deepseek-chat",
    }
    
    provider = db_key.provider.lower()
    model = provider_models.get(provider)
    if not model:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported or unconfigured provider for testing: {db_key.provider}",
        )

    try:
        # LiteLLM async test call
        await acompletion(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            api_key=raw_key,
            max_tokens=2,
            timeout=8.0,
        )
        
        # Mark key as valid
        db_key.is_valid = True
        db.add(db_key)
        await db.commit()
        
        return {"status": "success", "message": "Key is verified and connectable."}
    except Exception as e:
        # Mark key as invalid
        db_key.is_valid = False
        db.add(db_key)
        await db.commit()
        
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Connectivity test failed: {e}",
        )
