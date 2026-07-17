from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.provider_registry import provider_registry_service
from app.schemas.provider import ProviderRegistryRead, ProviderRegistryUpdate, ProviderToggle

router = APIRouter()


@router.get("", response_model=List[ProviderRegistryRead])
async def list_providers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all registered providers."""
    providers = await provider_registry_service.get_all(db)
    return providers


@router.get("/capabilities")
async def get_capabilities(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get capabilities matrix for all providers."""
    return await provider_registry_service.get_capabilities_matrix(db)


@router.get("/{slug}", response_model=ProviderRegistryRead)
async def get_provider(
    slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get provider details by slug."""
    provider = await provider_registry_service.get_by_slug(db, slug)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    return provider


@router.put("/{slug}", response_model=ProviderRegistryRead)
async def update_provider(
    slug: str,
    data: ProviderRegistryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update provider configuration."""
    update_data = data.model_dump(exclude_unset=True)
    provider = await provider_registry_service.update(db, slug, update_data)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    return provider


@router.post("/{slug}/toggle", response_model=ProviderRegistryRead)
async def toggle_provider(
    slug: str,
    data: ProviderToggle,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Enable or disable a provider."""
    provider = await provider_registry_service.toggle(db, slug, data.is_enabled)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    return provider
