import uuid
from typing import Optional, List, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.provider import ProviderRegistry
from app.models.api_key import ApiKey
from app.models.user import User
from app.services.provider_registry import provider_registry_service
from app.services.api_key_service import api_key_service
from app.services.health_monitor import health_monitor
from app.services.cost_estimator import cost_estimator
from app.schemas.health import ModelRoute

# Feature requirements
FEATURE_REQUIREMENTS = {
    "code_review": {"min_context_window": 8000, "supports_streaming": True},
    "security_scan": {"supports_function_calling": True},
    "documentation": {"min_context_window": 16000},
    "testing": {"min_context_window": 8000},
    "summarization": {"min_context_window": 4000},
}


class ModelRouter:
    async def route(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        feature: str,
        preferred_provider: Optional[str] = None,
        preferred_model: Optional[str] = None,
    ) -> List[ModelRoute]:
        user = await db.get(User, user_id)
        user_settings = {}
        if user and hasattr(user, "settings") and user.settings:
            user_settings = user.settings if isinstance(user.settings, dict) else {}

        routing_prefs = user_settings.get("model_routing", {})

        if feature in routing_prefs and not preferred_provider:
            pref = routing_prefs[feature]
            preferred_provider = pref.get("provider")
            preferred_model = pref.get("model")

        user_keys = await api_key_service.get_all_usable_keys(db, user_id)
        providers = await provider_registry_service.get_enabled(db)

        # Get feature requirements
        reqs = FEATURE_REQUIREMENTS.get(feature, {})

        routes = []
        for provider in providers:
            if provider.name not in user_keys:
                continue

            if not await health_monitor.should_allow_request(db, provider.name):
                continue

            # Apply feature requirements filtering
            if reqs.get("supports_streaming") and not provider.supports_streaming:
                continue
            if reqs.get("supports_function_calling") and not provider.supports_function_calling:
                continue
            if reqs.get("supports_vision") and not provider.supports_vision:
                continue
            if reqs.get("supports_reasoning") and not provider.supports_reasoning:
                continue

            key = user_keys[provider.name]
            model = preferred_model if (preferred_provider == provider.name and preferred_model) else provider.default_model

            cost = cost_estimator.estimate(provider.name, 1000, 1000)

            routes.append(ModelRoute(
                provider=provider.name,
                model=model,
                litellm_model=f"{provider.litellm_provider}/{model}",
                api_key_id=str(key.id),
                estimated_cost_per_1k=cost,
            ))

        if preferred_provider:
            routes.sort(key=lambda r: (0 if r.provider == preferred_provider else 1, r.estimated_cost_per_1k))
        else:
            routes.sort(key=lambda r: r.estimated_cost_per_1k)

        return routes

    async def get_available_routes(
        self, db: AsyncSession, user_id: uuid.UUID, feature: str,
    ) -> List[ModelRoute]:
        return await self.route(db, user_id, feature)

    def get_feature_requirements(self, feature: str) -> dict:
        return FEATURE_REQUIREMENTS.get(feature, {})


model_router = ModelRouter()
