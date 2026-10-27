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
            blocked = disabled_overrides.get(prov_name)
            if blocked:
                models = [m for m in models if m not in blocked]
            all_models[prov_name] = models
        except Exception:
            all_models[prov_name] = []

    return all_models
