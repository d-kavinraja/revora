import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional

import litellm
from app.ai.model_registry import CanonicalModel, canonical_registry

logger = logging.getLogger(__name__)

# Global in-memory cache for model discovery.
# Structure: { "api_key": { "timestamp": datetime, "models": List[Dict[str, Any]] } }
_MODEL_CACHE: Dict[str, Dict[str, Any]] = {}
CACHE_TTL = timedelta(hours=1)

class ModelDiscoveryEngine:
    """
    Production-grade Model Discovery Engine.
    Fetches models using litellm, validates accessibility, enriches with metadata,
    and caches the results.
    """

    LITELLM_PROVIDER_MAP = {
        "gemini": "gemini",
        "openai": "openai",
        "anthropic": "anthropic",
        "deepseek": "deepseek",
        "groq": "groq",
        "grok": "xai",
    }

    # Terms indicating a model is not a chat model, or is too specific.
    NON_CHAT_EXCLUSIONS = [
        "dall-e", "whisper", "embedding", "tts", "veo", "imagen", "lyria",
        "moderation", "speech", "audio", "video", "clip", "rerank", "vision",
        "image-generation", "image-preview", "1024-x", "1536-x", "512-x",
        "learnlm", "aqa", "bison", "gemini-1.0", "chat-bison", "text-bison",
        "gecko"
    ]

    DEPRECATED_TERMS = ["-001", "-0314", "-0613", "legacy", "deprecated"]
    PREVIEW_TERMS = ["preview", "exp-", "experimental", "rc", "alpha", "beta", "latest", "-2.0-", "-2.5-", "2.0-", "2.5-"]
    ENTERPRISE_TERMS = ["enterprise", "provisioned"]

    @classmethod
    async def get_available_models(cls, provider: str, raw_key: str) -> List[Dict[str, Any]]:
        """
        Get enriched model metadata for a specific provider and API key.
        Uses caching to prevent excessive API calls.
        """
        litellm_prov = cls.LITELLM_PROVIDER_MAP.get(provider.lower())
        if not litellm_prov:
            return []

        # Check cache
        cache_key = f"{litellm_prov}:{raw_key}"
        cached = _MODEL_CACHE.get(cache_key)
        now = datetime.now(timezone.utc)

        if cached and (now - cached["timestamp"]) < CACHE_TTL:
            return cached["models"]

        live_models: List[str] = []
        try:
            # Query the provider's actual API endpoint
            live_models = await asyncio.to_thread(
                litellm.get_valid_models,
                check_provider_endpoint=True,
                custom_llm_provider=litellm_prov,
                api_key=raw_key,
            )
        except Exception as e:
            logger.warning(f"Live model fetch failed for provider '{provider}': {e}")
            return []

        if not live_models:
            return []

        enriched_models = []
        for model_name in live_models:
            m_lower = model_name.lower()
            
            # Exclude non-chat models entirely (they shouldn't be selectable for code review)
            if any(ex in m_lower for ex in cls.NON_CHAT_EXCLUSIONS):
                continue

            canonical_model = cls._enrich_model(model_name, provider)
            enriched_models.append(canonical_model)

        # Run concurrent quota checks for all discovered models
        async def verify_and_update(c_model: CanonicalModel):
            has_quota = await cls.verify_model_quota(c_model, raw_key)
            c_model.accessible = has_quota
            canonical_registry.register(c_model)
            return c_model.model_dump()
            
        validated_models = await asyncio.gather(*(verify_and_update(m) for m in enriched_models))
        
        # Filter out models that failed the quota check so they don't clutter the UI
        final_models = [m for m in validated_models if m["accessible"]]

        # Update cache
        _MODEL_CACHE[cache_key] = {
            "timestamp": now,
            "models": final_models
        }

        return final_models

    @classmethod
    def _enrich_model(cls, model_name: str, provider: str) -> CanonicalModel:
        """
        Add detailed metadata to a model name and build a CanonicalModel.
        """
        m_lower = model_name.lower()
        provider_lower = provider.lower()
        
        provider_model_name = model_name
        canonical_model_name = model_name
        litellm_model_name = model_name
        
        # Normalization logic
        if provider_lower == "gemini":
            if model_name.startswith("gemini/"):
                canonical_model_name = model_name.split("/", 1)[1]
            elif model_name.startswith("models/"):
                canonical_model_name = model_name.split("/", 1)[1]
            litellm_model_name = f"gemini/{canonical_model_name}"
        elif provider_lower == "anthropic" and not model_name.startswith("anthropic/"):
            litellm_model_name = f"anthropic/{canonical_model_name}"
        elif provider_lower == "deepseek" and not model_name.startswith("deepseek/"):
            litellm_model_name = f"deepseek/{canonical_model_name}"
        elif provider_lower == "groq" and not model_name.startswith("groq/"):
            litellm_model_name = f"groq/{canonical_model_name}"
        elif provider_lower == "grok" and not model_name.startswith("xai/"):
            litellm_model_name = f"xai/{canonical_model_name}"

        is_deprecated = any(term in m_lower for term in cls.DEPRECATED_TERMS)
        is_preview = any(term in m_lower for term in cls.PREVIEW_TERMS)
        is_enterprise = any(term in m_lower for term in cls.ENTERPRISE_TERMS)
        
        # Check litellm model cost / info mapping if available
        info = litellm.model_cost.get(litellm_model_name, {})
        if not info and litellm_model_name != canonical_model_name:
             info = litellm.model_cost.get(canonical_model_name, {})

        context_window = info.get("max_tokens") or info.get("max_input_tokens") or None
        input_cost = info.get("input_cost_per_token") or info.get("input_cost_per_prompt_token") or 0.0
        output_cost = info.get("output_cost_per_token") or info.get("output_cost_per_completion_token") or 0.0
        
        supports_vision = info.get("supports_vision", False)
        supports_function_calling = info.get("supports_function_calling", False)
        supports_streaming = info.get("supports_streaming", True)
        
        status = "available"
        if is_deprecated:
            status = "deprecated"
        elif is_preview:
            status = "preview"
        elif is_enterprise:
            status = "enterprise"

        return CanonicalModel(
            provider=provider,
            provider_model_name=provider_model_name,
            canonical_model_name=canonical_model_name,
            litellm_model_name=litellm_model_name,
            model_name=canonical_model_name,
            accessible=True,
            deprecated=is_deprecated,
            preview=is_preview,
            experimental=is_preview,
            enterprise_only=is_enterprise,
            region_supported=True,
            context_window=context_window,
            input_cost=input_cost,
            output_cost=output_cost,
            supports_streaming=supports_streaming,
            supports_function_calling=supports_function_calling,
            supports_vision=supports_vision,
            supports_reasoning="reasoning" in m_lower or "o1" in m_lower,
            status=status,
            validation_timestamp=datetime.now(timezone.utc).isoformat()
        )

    @classmethod
    async def verify_model_quota(cls, canonical_model: CanonicalModel, raw_key: str) -> bool:
        """
        Executes a 1-token smoke test to verify if the API key has quota for this model.
        Returns True if successful, False if 429/403.
        """
        try:
            await asyncio.wait_for(
                asyncio.to_thread(
                    litellm.completion,
                    model=canonical_model.litellm_model_name,
                    messages=[{"role": "user", "content": "hi"}],
                    api_key=raw_key,
                    max_tokens=1,
                    drop_params=True
                ),
                timeout=5
            )
            return True
        except Exception as e:
            error_str = str(e).lower()
            if "429" in error_str or "quota" in error_str or "rate" in error_str or "403" in error_str or "forbidden" in error_str:
                logger.warning(f"Quota verification failed for {canonical_model.canonical_model_name}: {e}")
                return False
                
            # If LiteLLM doesn't support the mapping, try native fallback for Gemini
            if canonical_model.provider.lower() == "gemini" and ("404" in error_str or "not found" in error_str or "unsupported" in error_str):
                try:
                    from app.ai.llm import llm_service
                    await asyncio.wait_for(
                        llm_service._native_gemini_fallback(
                            canonical_model.canonical_model_name, 
                            [{"role": "user", "content": "hi"}], 
                            raw_key, 
                            timeout=5
                        ),
                        timeout=5
                    )
                    return True
                except Exception as fallback_e:
                    f_error_str = str(fallback_e).lower()
                    if "429" in f_error_str or "quota" in f_error_str or "403" in f_error_str:
                        logger.warning(f"Native fallback quota verification failed for {canonical_model.canonical_model_name}: {fallback_e}")
                        return False
                        
            # If it fails for other reasons (e.g. 500, timeout), assume it's accessible so we don't erroneously hide it
            return True

    @classmethod
    async def validate_model_access(cls, provider: str, model_name: str, raw_key: str) -> bool:
        """
        Validates if a specific model is accessible with the given key using compatibility engine.
        """
        available = await cls.get_available_models(provider, raw_key)
        for m in available:
            # We must resolve based on canonical, provider, or litellm name
            if model_name in [m["canonical_model_name"], m["litellm_model_name"], m["provider_model_name"], m.get("model_name", "")]:
                return m["accessible"] and not m["deprecated"]
        return False

    @classmethod
    def invalidate_cache(cls, provider: str, raw_key: str):
        litellm_prov = cls.LITELLM_PROVIDER_MAP.get(provider.lower())
        if not litellm_prov:
            return
        cache_key = f"{litellm_prov}:{raw_key}"
        if cache_key in _MODEL_CACHE:
            del _MODEL_CACHE[cache_key]

model_discovery_engine = ModelDiscoveryEngine()
