import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User
from app.schemas.health import ModelRoute
from app.services.api_key_service import api_key_service
from app.services.cost_estimator import cost_estimator
from app.services.model_overrides import model_overrides_service
from app.services.provider_registry import provider_registry_service

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
        preferred_provider: str | None = None,
        preferred_model: str | None = None,
    ) -> list[ModelRoute]:
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
        # Status-aware selection: only enabled providers with `available`
        # status may serve new reviews (phase 4, §9.3 #6). Zero-state parity:
        # all seeded rows default to available/enabled.
        providers = await provider_registry_service.get_usable(db)
        # Per-model overrides (phase 6, §11.2): a disabled model is skipped —
        # the provider and its other models stay usable.
        disabled_overrides = await model_overrides_service.get_disabled_map(db)

        # Get feature requirements
        reqs = FEATURE_REQUIREMENTS.get(feature, {})

        # Managed providers (kLLM, kLLM Cloud) need no user key; they only need
        # live readiness. Load that once so the loop stays O(1) per provider.
        # Cloud readiness is its own approval set: a cloud model is never
        # implied by local kLLM readiness or vice versa.
        managed_ready: set[str] = set()
        cloud_ready: set[str] = set()
        if settings.KLLM_ENABLED and any(p.is_managed for p in providers):
            from app.services.kllm_service import get_ready_models

            managed_ready = {m.key for m in await get_ready_models(db)}
        if settings.KLLM_CLOUD_ENABLED and any(
            p.is_managed and p.slug == "kllm-cloud" for p in providers
        ):
            from app.services import kllm_cloud_service

            cloud_ready = {
                m.model_id for m in await kllm_cloud_service.get_review_models(db)
            }

        routes = []
        for provider in providers:
            if not provider.is_managed and provider.name not in user_keys:
                continue

            # Apply feature requirements filtering
            if reqs.get("supports_streaming") and not provider.supports_streaming:
                continue
            if (
                reqs.get("supports_function_calling")
                and not provider.supports_function_calling
            ):
                continue
            if reqs.get("supports_vision") and not provider.supports_vision:
                continue
            if reqs.get("supports_reasoning") and not provider.supports_reasoning:
                continue

            if provider.is_managed:
                # Never silently substitute: an explicitly requested managed
                # model must be ready for its own provider, otherwise the
                # provider is skipped and the caller fails fast downstream.
                is_cloud = provider.slug == "kllm-cloud"
                ready_set = cloud_ready if is_cloud else managed_ready
                wanted = preferred_model
                if is_cloud and wanted:
                    from app.services.kllm_cloud_service import model_id_from_key

                    wanted = model_id_from_key(wanted) or wanted
                if preferred_provider == provider.name and wanted:
                    if wanted not in ready_set:
                        continue
                    model = wanted
                else:
                    if provider.default_model in ready_set:
                        model = provider.default_model
                    elif ready_set:
                        model = sorted(ready_set)[0]
                    else:
                        continue
                key_id = None
            else:
                key = user_keys[provider.name]
                model = (
                    preferred_model
                    if (preferred_provider == provider.name and preferred_model)
                    else provider.default_model
                )
                key_id = str(key.id)

            if model in disabled_overrides.get(provider.name, ()):
                continue

            cost = cost_estimator.estimate(provider.name, 1000, 1000)

            routes.append(
                ModelRoute(
                    provider=provider.name,
                    model=model,
                    litellm_model=f"{provider.litellm_provider}/{model}",
                    api_key_id=key_id,
                    estimated_cost_per_1k=cost,
                )
            )

        if preferred_provider:
            routes.sort(
                key=lambda r: (
                    0 if r.provider == preferred_provider else 1,
                    r.estimated_cost_per_1k,
                )
            )
        else:
            routes.sort(key=lambda r: r.estimated_cost_per_1k)

        return routes

    async def get_available_routes(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        feature: str,
    ) -> list[ModelRoute]:
        return await self.route(db, user_id, feature)

    async def route_excluding(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        feature: str,
        *,
        exclude: set[tuple[str, str]] | None = None,
    ) -> ModelRoute | None:
        """Return the first eligible route that is not in ``exclude``.

        Used by repository fallback: the existing ranked candidate list stays
        authoritative, only the failed primary pair is skipped.
        """
        routes = await self.route(db, user_id, feature)
        excluded = exclude or set()
        for route in routes:
            if (route.provider, route.model) in excluded:
                continue
            return route
        return None

    def get_feature_requirements(self, feature: str) -> dict:
        return FEATURE_REQUIREMENTS.get(feature, {})


model_router = ModelRouter()
