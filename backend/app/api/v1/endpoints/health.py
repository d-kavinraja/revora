from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.health_monitor import health_monitor
from app.services.api_key_service import api_key_service
from app.schemas.health import ProviderHealthRead, FailoverLogRead, HealthDashboard

router = APIRouter()


@router.get("/providers", response_model=List[ProviderHealthRead])
async def list_provider_health(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get health status for providers registered by the current user."""
    user_keys = await api_key_service.get_all_for_user(db, current_user.id)
    user_providers = {k.provider.lower() for k in user_keys if k.provider}

    for p in user_providers:
        await health_monitor.get_or_create(db, p)

    all_health = await health_monitor.get_all_health(db)
    return [h for h in all_health if h.provider.lower() in user_providers]


@router.get("/providers/{provider}", response_model=ProviderHealthRead)
async def get_provider_health(
    provider: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get health status for a specific provider."""
    health = await health_monitor.get_health(db, provider)
    if not health:
        raise HTTPException(status_code=404, detail="Provider health not found")
    return health


@router.post("/providers/{provider}/check")
async def check_provider_health(
    provider: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Run an on-demand health check for a provider."""
    health = await health_monitor.get_or_create(db, provider)
    return {"provider": provider, "status": health.status, "circuit_state": health.circuit_state}


@router.get("/failovers", response_model=List[FailoverLogRead])
async def list_failovers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get recent failover events for the user."""
    return await health_monitor.get_recent_failovers(db, current_user.id)


@router.get("/circuit-breakers")
async def get_circuit_breakers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get circuit breaker states for user-registered providers."""
    user_keys = await api_key_service.get_all_for_user(db, current_user.id)
    user_providers = {k.provider.lower() for k in user_keys if k.provider}
    all_cb = await health_monitor.get_circuit_breakers(db)
    return {prov: state for prov, state in all_cb.items() if prov.lower() in user_providers}
