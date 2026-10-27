import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.discovery.engine import discovery_engine
from app.core.deps import get_current_user
from app.core.deps_admin import get_current_admin_or_403
from app.db.session import get_db
from app.middleware.rate_limit import limiter
from app.models.admin import AdminUser
from app.models.user import User
from app.schemas.provider import (
    DiscoveredModelRead,
    ProviderRegistryPublic,
    ProviderRegistryRead,
    ProviderRegistryUpdate,
    ProviderToggle,
)
from app.services.admin_audit import admin_audit
from app.services.provider_registry import provider_registry_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=list[ProviderRegistryPublic])
async def list_providers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all registered providers (internal wiring fields withheld)."""
    providers = await provider_registry_service.get_all(db)
    return providers


@router.get("/capabilities")
async def get_capabilities(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get capabilities matrix for all providers."""
    return await provider_registry_service.get_capabilities_matrix(db)


@router.get("/{slug}", response_model=ProviderRegistryPublic)
async def get_provider(
    slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get provider details by slug (internal wiring fields withheld)."""
    provider = await provider_registry_service.get_by_slug(db, slug)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    return provider


@router.put("/{slug}", response_model=ProviderRegistryRead)
@limiter.limit("30/minute")
async def update_provider(
    request: Request,
    slug: str,
    data: ProviderRegistryUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin_or_403),
):
    """Update provider configuration (admin-only, audited)."""
    update_data = data.model_dump(exclude_unset=True)
    provider = await provider_registry_service.update(db, slug, update_data)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    await admin_audit(
        db,
        action="admin.provider_status_changed",
        entity_type="provider",
        entity_id=slug,
        admin=current_admin,
        request=request,
        details={"changes": update_data, "route": "legacy"},
    )
    return provider


@router.post("/{slug}/toggle", response_model=ProviderRegistryRead)
@limiter.limit("30/minute")
async def toggle_provider(
    request: Request,
    slug: str,
    data: ProviderToggle,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin_or_403),
):
    """Enable or disable a provider (admin-only, audited)."""
    provider = await provider_registry_service.toggle(db, slug, data.is_enabled)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    await admin_audit(
        db,
        action="admin.provider_toggled",
        entity_type="provider",
        entity_id=slug,
        admin=current_admin,
        request=request,
        details={
            "changes": {"is_enabled": provider.is_enabled},
            "route": "legacy",
        },
    )
    return provider


@router.post("/{slug}/sync-models", response_model=list[DiscoveredModelRead])
@limiter.limit("30/minute")
async def sync_provider_models(
    request: Request,
    slug: str,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin_or_403),
):
    """Force sync provider models (admin-only, audited)."""
    try:
        models = await discovery_engine.sync_provider_models(db, slug, force=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Provider model sync failed for %s", slug)
        raise HTTPException(status_code=500, detail="Provider model sync failed")
    await admin_audit(
        db,
        action="admin.provider_models_synced",
        entity_type="provider",
        entity_id=slug,
        admin=current_admin,
        request=request,
        details={"count": len(models) if models else 0, "route": "legacy"},
    )
    return models


@router.get("/{slug}/models", response_model=list[DiscoveredModelRead])
async def get_provider_models(
    slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get cached provider models."""
    # Opportunistic background sync (will only run if TTL expired)
    try:
        await discovery_engine.sync_provider_models(db, slug, force=False)
    except Exception:
        pass # If background sync fails, just fall through to returning cached

    return await discovery_engine.get_cached_models(db, slug)
