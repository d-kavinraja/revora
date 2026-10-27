"""Admin provider controls (phase 4, §9 / §14 / §18).

`GET /admin/providers` returns provider rows plus stored usage/health
aggregates; `PUT /admin/providers/{slug}` applies a whitelisted status
update (status, message, ETA, master switch, key-addition policy) with
audit rows. Never touches credentials, mappings or history (S7).
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps_admin import get_current_admin
from app.db.session import get_db
from app.middleware.rate_limit import limiter
from app.models.admin import AdminUser
from app.models.api_key import ApiKey
from app.models.discovered_model import DiscoveredModel
from app.models.github import Repository
from app.models.health import ProviderHealth
from app.models.provider import ProviderRegistry
from app.schemas.admin import (
    AdminProviderListResponse,
    AdminProviderRead,
    AdminProviderUpdate,
)
from app.services.admin_audit import admin_audit
from app.services.provider_registry import VALID_STATUSES, provider_registry_service

router = APIRouter()


async def _keys_by_provider(db: AsyncSession) -> dict[str, dict[str, int]]:
    result = await db.execute(
        select(
            ApiKey.provider,
            func.count(ApiKey.id),
            func.sum(case((ApiKey.is_enabled == True, 1), else_=0)),
            func.sum(case((ApiKey.is_valid == True, 1), else_=0)),
        ).group_by(ApiKey.provider)
    )
    aggregates: dict[str, dict[str, int]] = {}
    for provider, total, enabled, valid in result.all():
        aggregates[(provider or "").lower()] = {
            "total": int(total or 0),
            "enabled": int(enabled or 0),
            "valid": int(valid or 0),
        }
    return aggregates


async def _discovered_models_by_provider(db: AsyncSession) -> dict[str, int]:
    result = await db.execute(
        select(DiscoveredModel.provider_slug, func.count(DiscoveredModel.id)).group_by(
            DiscoveredModel.provider_slug
        )
    )
    return {str(slug).lower(): int(count or 0) for slug, count in result.all()}


async def _mapped_repositories(db: AsyncSession) -> dict[str, int]:
    result = await db.execute(
        select(Repository.settings).where(Repository.settings.is_not(None))
    )
    counts: dict[str, int] = {}
    for (settings,) in result.all():
        if not isinstance(settings, dict):
            continue
        provider = settings.get("assigned_provider")
        if provider and settings.get("assigned_model"):
            counts[str(provider).lower()] = counts.get(str(provider).lower(), 0) + 1
    return counts


async def _latest_health(db: AsyncSession) -> dict[str, tuple[str, object]]:
    latest = (
        select(
            ProviderHealth.provider,
            func.max(ProviderHealth.created_at).label("ts"),
        )
        .group_by(ProviderHealth.provider)
        .subquery()
    )
    result = await db.execute(
        select(ProviderHealth.provider, ProviderHealth.status, ProviderHealth.created_at)
        .join(
            latest,
            and_(
                ProviderHealth.provider == latest.c.provider,
                ProviderHealth.created_at == latest.c.ts,
            ),
        )
    )
    return {
        (provider or "").lower(): (row_status, created_at)
        for provider, row_status, created_at in result.all()
    }


def _to_read(
    provider: ProviderRegistry,
    keys: dict[str, dict[str, int]],
    repos: dict[str, int],
    health: dict[str, tuple[str, object]],
    models: dict[str, int] | None = None,
) -> AdminProviderRead:
    key_stats = keys.get(provider.name.lower(), {"total": 0, "enabled": 0, "valid": 0})
    health_row = health.get(provider.name.lower())
    models = models or {}
    return AdminProviderRead(
        id=provider.id,
        name=provider.name,
        display_name=provider.display_name,
        slug=provider.slug,
        default_model=provider.default_model,
        priority=provider.priority,
        is_enabled=provider.is_enabled,
        status=provider.status,
        status_message=provider.status_message,
        status_expires_at=provider.status_expires_at,
        allow_key_addition=provider.allow_key_addition,
        supports_streaming=provider.supports_streaming,
        supports_vision=provider.supports_vision,
        supports_function_calling=provider.supports_function_calling,
        supports_reasoning=provider.supports_reasoning,
        keys_total=key_stats["total"],
        keys_enabled=key_stats["enabled"],
        keys_valid=key_stats["valid"],
        mapped_repositories=repos.get(provider.name.lower(), 0),
        models_count=models.get(provider.slug.lower(), 0) or models.get(provider.name.lower(), 0),
        last_health_status=health_row[0] if health_row else None,
        last_health_at=health_row[1] if health_row else None,
    )


async def build_provider_rows(db: AsyncSession) -> list[AdminProviderRead]:
    providers = await provider_registry_service.get_all(db)
    keys = await _keys_by_provider(db)
    repos = await _mapped_repositories(db)
    health = await _latest_health(db)
    models = await _discovered_models_by_provider(db)
    return [_to_read(p, keys, repos, health, models) for p in providers]


@router.get("/providers", response_model=AdminProviderListResponse)
async def list_admin_providers(
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """All providers with stored usage/health aggregates (admin only)."""
    return AdminProviderListResponse(items=await build_provider_rows(db))


@router.put("/providers/{slug}", response_model=AdminProviderRead)
@limiter.limit("30/minute")
async def update_admin_provider(
    slug: str,
    data: AdminProviderUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Update provider status/policy (whitelisted fields, audited)."""
    provider = await provider_registry_service.get_by_slug(db, slug)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    changes = data.model_dump(exclude_unset=True)

    if changes.get("status") is not None and changes["status"] not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid provider status")

    # Contradictory master-switch/status pairs → 409 (consistency rule §9.1:
    # is_enabled=false ⇔ status='disabled').
    if (
        changes.get("is_enabled") is False
        and "status" in changes
        and changes.get("status") != "disabled"
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "is_enabled=false conflicts with the requested status — "
                "use status='disabled' to turn the provider off."
            ),
        )
    if changes.get("is_enabled") is True and changes.get("status") == "disabled":
        raise HTTPException(
            status_code=409,
            detail=(
                "is_enabled=true conflicts with status='disabled' — "
                "choose one of the two."
            ),
        )

    if any(
        field in changes for field in ("status", "status_message", "status_expires_at")
    ):
        action = "admin.provider_status_changed"
    elif "is_enabled" in changes:
        action = "admin.provider_toggled"
    elif "allow_key_addition" in changes:
        action = "admin.provider_keypolicy_changed"
    else:
        action = "admin.provider_status_changed"
    requested = sorted(changes.keys())

    # NOTE: `apply_admin_update` mutates `changes` in place (consistency
    # rule), so action/requested are derived from the request beforehand.
    provider, effective = await provider_registry_service.apply_admin_update(
        db, provider, changes
    )

    await admin_audit(
        db,
        action=action,
        entity_type="provider",
        entity_id=provider.slug,
        admin=current_admin,
        request=request,
        details={
            "changes": {
                key: (value.isoformat() if hasattr(value, "isoformat") else value)
                for key, value in effective.items()
            },
            "requested": requested,
        },
        commit=False,
    )
    await db.commit()
    await db.refresh(provider)

    keys = await _keys_by_provider(db)
    repos = await _mapped_repositories(db)
    health = await _latest_health(db)
    models = await _discovered_models_by_provider(db)
    return _to_read(provider, keys, repos, health, models)
