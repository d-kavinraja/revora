from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.security import encryption_service
from app.db.session import get_db
from app.models.user import User
from app.services.api_key_service import api_key_service
from app.services.model_discovery import model_discovery_engine

router = APIRouter()


@router.get("")
async def list_models(
    provider: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List available models for the current user's API keys."""
    user_keys = await api_key_service.get_all_usable_keys(db, current_user.id)

    all_models = {}
    for prov_name, key in user_keys.items():
        if provider and prov_name != provider:
            continue
        try:
            raw_key = encryption_service.decrypt(key.encrypted_key)
            models = await model_discovery_engine.get_available_models(
                prov_name, raw_key
            )
            all_models[prov_name] = models
        except Exception:
            all_models[prov_name] = []

    return all_models
