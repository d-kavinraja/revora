import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.deps_flags import require_feature
from app.core.security import encryption_service
from app.db.session import get_db
from app.models.user import User
from app.security.error_sanitizer import sanitize_error_message
from app.services.api_key_service import api_key_service
from app.services.model_discovery import model_discovery_engine
from app.services.model_overrides import model_overrides_service
from app.services.model_router import model_router
from app.services.provider_registry import provider_registry_service

logger = logging.getLogger(__name__)
router = APIRouter()


class RoutingPreferencesUpdate(BaseModel):
    routing: dict


@router.get("/routes")
async def get_routes(
    feature: str = "code_review",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get available routes for the current user."""
    routes = await model_router.get_available_routes(db, current_user.id, feature)
    return {"routes": [r.model_dump() for r in routes]}


@router.get("/models-per-provider")
async def get_models_per_provider(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get discovered models grouped by provider for the current user."""
    user_keys = await api_key_service.get_all_usable_keys(db, current_user.id)

    # Provider-status filter (C1): only available providers may be probed.
    usable_providers = {
        p.name for p in await provider_registry_service.get_usable(db)
    }
    user_keys = {
        name: key for name, key in user_keys.items() if name in usable_providers
    }
    disabled_overrides = await model_overrides_service.get_disabled_map(db)

    # Probe every provider concurrently: each branch is an independent external
    # HTTP round-trip (no DB access), so the endpoint costs the slowest provider
    # instead of the sum of all. Failures collapse to an empty list per provider,
    # matching the previous sequential behavior.

    async def _probe(provider_name: str, key) -> tuple[str, list[dict[str, str]]]:
        try:
            raw_key = encryption_service.decrypt(key.encrypted_key)
            models = await model_discovery_engine.get_available_models(
                provider_name, raw_key
            )
            blocked = disabled_overrides.get(provider_name) or set()
            return provider_name, [
                {
                    "model": m["canonical_model_name"],
                    "litellm_model": m["litellm_model_name"],
                }
                for m in models
                if m.get("accessible", True)
                and (
                    m.get("canonical_model_name")
                    or m.get("model_name")
                    or m.get("model")
                )
                not in blocked
            ]
        except Exception:
            return provider_name, []

    probe_results = await asyncio.gather(
        *(
            _probe(provider_name, key)
            for provider_name, key in user_keys.items()
        )
    )
    grouped = dict(probe_results)

    # Managed providers expose a server-owned catalogue and need no user key.
    # Each provider reads its own source: kLLM Cloud options come from the
    # cloud snapshot/approval gate and must never be served from local kLLM
    # readiness (which would fabricate cloud models on a local-only install).
    from app.services import kllm_cloud_service

    for provider in await provider_registry_service.get_usable(db):
        if not provider.is_managed:
            continue
        if provider.name in user_keys:
            continue
        try:
            if provider.slug == kllm_cloud_service.PROVIDER_SLUG:
                models = await kllm_cloud_service.model_options(db, surface="review")
            else:
                from app.services import kllm_service

                models = await kllm_service.get_model_options(db)
        except Exception:  # noqa: BLE001 - never leak provider details
            grouped[provider.name] = []
            continue
        blocked = disabled_overrides.get(provider.name, set()) | (
            disabled_overrides.get(provider.slug, set())
        )
        grouped[provider.name] = [
            {
                "model": m["canonical_model_name"],
                "litellm_model": m.get("litellm_model_name")
                or f"{provider.litellm_provider}/{m['canonical_model_name']}",
            }
            for m in models
            if m["canonical_model_name"] not in blocked
            and m.get("model_id", m["canonical_model_name"]) not in blocked
        ]

    return grouped


@router.get("/recommend/{feature}")
async def recommend_route(
    feature: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the recommended route for a specific feature."""
    routes = await model_router.route(db, current_user.id, feature)
    if not routes:
        raise HTTPException(
            status_code=404,
            detail="No available routes. Add an API key for a supported provider.",
        )
    return routes[0].model_dump()


@router.get("/preferences")
async def get_routing_preferences(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get per-feature routing preferences."""
    user = await db.get(User, current_user.id)
    if not user or not user.settings:
        return {"routing": {}}
    return {"routing": user.settings.get("model_routing", {})}


@router.put("/preferences")
async def update_routing_preferences(
    data: RoutingPreferencesUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_feature("routing_mapping")),
):
    """Update per-feature routing preferences."""
    try:
        user = await db.get(User, current_user.id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Initialize settings if not present
        if not hasattr(user, "settings") or user.settings is None:
            user.settings = {}

        if not isinstance(user.settings, dict):
            user.settings = {}

        # Phase 4: blocked providers cannot be stored as preferences
        # (additive check — zero-state flows unchanged).
        for feature_pref in (data.routing or {}).values():
            if not isinstance(feature_pref, dict):
                continue
            pref_provider = feature_pref.get("provider")
            if not pref_provider:
                continue
            usable, provider_row = await provider_registry_service.usability(
                db, pref_provider
            )
            if not usable:
                detail = (
                    provider_row.status_message
                    if provider_row is not None and provider_row.status_message
                    else f"Provider '{pref_provider}' is not available for new routing preferences."
                )
                raise HTTPException(status_code=400, detail=detail)

            # Managed providers validate against their own gate. The local
            # kLLM gate knows nothing about Cloud models (and a same-named
            # local model must not validate a Cloud one), so Cloud uses its
            # approval/surface/readiness check. Never substitute another model.
            if provider_row is not None and provider_row.is_managed:
                pref_model = feature_pref.get("model")
                if pref_model:
                    from app.services import kllm_cloud_service
                    from app.services.kllm_cloud_errors import KllmCloudError
                    from app.services.kllm_service import (
                        KllmError,
                        ensure_model_selectable,
                    )

                    try:
                        if provider_row.slug == kllm_cloud_service.PROVIDER_SLUG:
                            await kllm_cloud_service.ensure_model_ready(
                                db, pref_model, surface="review"
                            )
                        else:
                            await ensure_model_selectable(db, pref_model)
                    except KllmCloudError as exc:
                        raise HTTPException(
                            status_code=400, detail=exc.message
                        ) from exc
                    except KllmError as exc:
                        raise HTTPException(
                            status_code=400, detail=exc.message
                        ) from exc

        # Update model_routing
        user.settings["model_routing"] = data.routing

        # Force update by marking the attribute as modified
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(user, "settings")

        db.add(user)
        await db.commit()
        await db.refresh(user)

        logger.info(
            f"Updated routing preferences for user {current_user.id}: {data.routing}"
        )
        return {"status": "updated", "routing": data.routing}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update routing preferences: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save preferences: {sanitize_error_message(e)}",
        )
