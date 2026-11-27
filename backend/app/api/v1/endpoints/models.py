from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.deps_flags import require_feature
from app.core.security import encryption_service
from app.db.session import get_db
from app.models.user import User
from app.services.api_key_service import api_key_service
from app.services.model_discovery import model_discovery_engine
from app.services.model_overrides import model_overrides_service
from app.services.provider_registry import provider_registry_service

router = APIRouter()


def _model_name(model: Any) -> str:
    if isinstance(model, str):
        return model
    if isinstance(model, dict):
        return str(
            model.get("canonical_model_name")
            or model.get("model_name")
            or model.get("model")
            or ""
        )
    return str(model)


@router.get("")
async def list_models(
    provider: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_feature("model_lab")),
):
    """List available models for the current user's API keys."""
    user_keys = await api_key_service.get_all_usable_keys(db, current_user.id)
    disabled_overrides = await model_overrides_service.get_disabled_map(db)

    # Provider-status filter (C1): only providers with available status may
    # contribute models.
    usable_providers = {
        p.name for p in await provider_registry_service.get_usable(db)
    }

    all_models = {}
    for prov_name, key in user_keys.items():
        if prov_name not in usable_providers:
            continue
        if provider and prov_name != provider:
            continue
        try:
            raw_key = encryption_service.decrypt(key.encrypted_key)
            models = await model_discovery_engine.get_available_models(
                prov_name, raw_key
            )
            blocked = disabled_overrides.get(prov_name) or set()
            if blocked:
                models = [
                    m
                    for m in models
                    if _model_name(m) not in blocked
                ]
            all_models[prov_name] = models
        except Exception:
            all_models[prov_name] = []

    # Managed providers expose a server-owned catalogue and need no user key.
    # Each provider reads its own source, so Cloud options come from the cloud
    # approval gate and local kLLM readiness never fabricates cloud models.
    from app.services import kllm_cloud_service

    for prov in await provider_registry_service.get_usable(db):
        if not prov.is_managed:
            continue
        if provider and prov.name != provider:
            continue
        try:
            if prov.slug == kllm_cloud_service.PROVIDER_SLUG:
                all_models[prov.name] = await kllm_cloud_service.model_options(
                    db, surface="chat"
                )
            else:
                from app.services import kllm_service

                all_models[prov.name] = await kllm_service.get_model_options(db)
        except Exception:  # noqa: BLE001 - never leak provider details
            all_models[prov.name] = []

    return all_models
