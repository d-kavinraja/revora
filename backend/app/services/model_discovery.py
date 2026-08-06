import asyncio
import hashlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import litellm

from app.ai.model_registry import CanonicalModel, canonical_registry

logger = logging.getLogger(__name__)

# Global in-memory cache for model discovery.
_MODEL_CACHE: dict[str, dict[str, Any]] = {}
CACHE_TTL = timedelta(hours=1)

def _hash_api_key(raw_key: str) -> str:
    """Hash API key for secure cache storage."""
    return hashlib.sha256(raw_key.encode()).hexdigest()[:16]

class ModelDiscoveryEngine:
    """
    Production-grade Model Discovery Engine.
    Fetches models using litellm, validates accessibility, enriches with metadata,
    and caches the results.
    """

    LITELLM_PROVIDER_MAP: ClassVar[dict[str, str]] = {
        "gemini": "gemini",
        "openai": "openai",
        "anthropic": "anthropic",
        "deepseek": "deepseek",
        "groq": "groq",
        "grok": "xai",
        "openrouter": "openrouter",
        "azure_openai": "azure",
        "ollama": "ollama",
        "cohere": "cohere",
        "mistral": "mistral",
        "nvidia": "nvidia_nim",
    }

    # Terms indicating a model is not a chat model
    NON_CHAT_EXCLUSIONS: ClassVar[list[str]] = [
        "dall-e", "whisper", "embedding", "embed", "tts", "veo", "imagen", "lyria",
        "moderation", "speech", "audio", "video", "clip", "rerank",
        "image-generation", "image-preview", "1024-x", "1536-x", "512-x",
        "learnlm", "aqa", "bison", "chat-bison", "text-bison", "gecko",
        "reward", "guardrail", "bge-", "deplot", "diffusion"
    ]

    RECOMMENDED_MODELS: ClassVar[list[str]] = [
        "meta/llama-3.3-70b-instruct",
        "deepseek-ai/deepseek-v4-flash",
        "minimaxai/minimax-m3",
        "meta/llama-3.1-70b-instruct",
        "nvidia/llama-3.1-nemotron-70b-instruct",
        "deepseek-ai/deepseek-r1",
        "mistralai/mistral-large-2-instruct",
        "bigcode/starcoder2-15b",
        "qwen/qwen2.5-coder-32b-instruct",
        "meta/llama-3.1-8b-instruct",
    ]

    # Gemini 2.0/2.5 models have severe rate limits on both free and paid tiers
    # Excluding them entirely - users should use 1.5, 3, or Gemma models
    GEMINI_RATE_LIMITED_MODELS: ClassVar[list[str]] = [
        "gemini-2.0", "gemini-2.5", "gemini-2.0-flash", "gemini-2.5-flash",
        "gemini-2.5-pro", "gemini-2.0-flash-lite", "gemini-2.5-flash-lite",
    ]

    DEPRECATED_TERMS: ClassVar[list[str]] = ["-001", "-0314", "-0613", "legacy", "deprecated"]
    PREVIEW_TERMS: ClassVar[list[str]] = ["preview", "exp-", "experimental", "rc", "alpha", "beta"]
    ENTERPRISE_TERMS: ClassVar[list[str]] = ["enterprise", "provisioned"]

    @classmethod
    async def get_available_models(cls, provider: str, raw_key: str) -> list[dict[str, Any]]:
        """
        Get enriched model metadata for a specific provider and API key.
        Uses caching to prevent excessive API calls.
        """
        litellm_prov = cls.LITELLM_PROVIDER_MAP.get(provider.lower())
        if not litellm_prov:
            return []

        # Check cache using hashed key
        cache_key = f"{litellm_prov}:{_hash_api_key(raw_key)}"
        cached = _MODEL_CACHE.get(cache_key)
        now = datetime.now(UTC)

        if cached and (now - cached["timestamp"]) < CACHE_TTL:
            return cached["models"]

        live_models: list[str] = []
        try:
            if litellm_prov == "nvidia_nim":
                try:
                    import httpx
                    headers = {"Authorization": f"Bearer {raw_key}"} if raw_key else {}
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        resp = await client.get("https://integrate.api.nvidia.com/v1/models", headers=headers)
                        if resp.status_code in (200, 401, 403):
                            data = resp.json().get("data", [])
                            live_models = [m["id"] for m in data if isinstance(m, dict) and "id" in m]
                except Exception as e:
                    logger.warning(f"Direct NVIDIA API model fetch failed: {e}")

                if not live_models:
                    live_models = [
                        "meta/llama-3.3-70b-instruct",
                        "meta/llama-3.1-70b-instruct",
                        "meta/llama-3.1-8b-instruct",
                        "deepseek-ai/deepseek-v4-flash",
                        "deepseek-ai/deepseek-r1",
                        "nvidia/llama-3.1-nemotron-70b-instruct",
                        "mistralai/mistral-large-2-instruct",
                        "bigcode/starcoder2-15b",
                    ]
            else:
                # Query the provider's actual API endpoint
                live_models = await asyncio.to_thread(
                    litellm.get_valid_models,
                    check_provider_endpoint=True,
                    custom_llm_provider=litellm_prov,
                    api_key=raw_key,
                )
        except Exception as e:
            error_str = str(e).lower()
            # Rate limiting is not a permanent failure - return empty but don't cache
            if "429" in error_str or "rate" in error_str or "quota" in error_str:
                logger.warning(f"Rate limited during model discovery for '{provider}': {e}")
                return []
            logger.warning(f"Live model fetch failed for provider '{provider}': {e}")
            return []

        if not live_models:
            return []

        enriched_models = []
        for model_name in live_models:
            m_lower = model_name.lower()

            # Exclude non-chat models
            if any(ex in m_lower for ex in cls.NON_CHAT_EXCLUSIONS):
                continue

            # Exclude Gemini 2.0/2.5 models due to severe rate limits
            if any(ex in m_lower for ex in cls.GEMINI_RATE_LIMITED_MODELS):
                logger.info(f"Skipping rate-limited Gemini model: {model_name}")
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

        # Filter out models that failed the quota check
        final_models = [m for m in validated_models if m["accessible"]]

        # Sort so recommended models appear at the top
        def get_model_priority(m: dict) -> int:
            name = m.get("canonical_model_name", "")
            if name in cls.RECOMMENDED_MODELS:
                return cls.RECOMMENDED_MODELS.index(name)
            return 999

        final_models.sort(key=get_model_priority)

        # Update cache with hashed key
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
            if model_name.startswith(("gemini/", "models/")):
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
        elif provider_lower == "openrouter" and not model_name.startswith("openrouter/"):
            litellm_model_name = f"openrouter/{canonical_model_name}"
        elif provider_lower == "azure_openai" and not model_name.startswith("azure/"):
            litellm_model_name = f"azure/{canonical_model_name}"
        elif provider_lower == "ollama" and not model_name.startswith("ollama/"):
            litellm_model_name = f"ollama/{canonical_model_name}"
        elif provider_lower == "cohere" and not model_name.startswith("cohere/"):
            litellm_model_name = f"cohere/{canonical_model_name}"
        elif provider_lower == "mistral" and not model_name.startswith("mistral/"):
            litellm_model_name = f"mistral/{canonical_model_name}"
        elif provider_lower == "nvidia" and not model_name.startswith("nvidia_nim/"):
            litellm_model_name = f"nvidia_nim/{canonical_model_name}"

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
            validation_timestamp=datetime.now(UTC).isoformat()
        )

    @classmethod
    async def verify_model_quota(cls, canonical_model: CanonicalModel, raw_key: str) -> bool:
        """
        Executes a 1-token smoke test to verify if the API key has quota for this model.
        Returns True if successful, False if 404/unsupported.
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
            if "404" in error_str or "not found" in error_str or "unsupported" in error_str:
                logger.warning(f"Model {canonical_model.canonical_model_name} not supported: {e}")
                return False

            # If it fails due to transient 403, 429, timeout or server error, retain model as accessible
            logger.info(f"Smoke test soft failure for {canonical_model.canonical_model_name}: {e}")
            return True

    @classmethod
    async def validate_model_access(cls, provider: str, model_name: str, raw_key: str) -> bool:
        """
        Validates if a specific model is accessible with the given key.
        """
        available = await cls.get_available_models(provider, raw_key)
        for m in available:
            if model_name in [m["canonical_model_name"], m["litellm_model_name"], m["provider_model_name"], m.get("model_name", "")]:
                return m["accessible"] and not m["deprecated"]
        return False

    @classmethod
    def invalidate_cache(cls, provider: str, raw_key: str):
        litellm_prov = cls.LITELLM_PROVIDER_MAP.get(provider.lower())
        if not litellm_prov:
            return
        cache_key = f"{litellm_prov}:{_hash_api_key(raw_key)}"
        _MODEL_CACHE.pop(cache_key, None)

model_discovery_engine = ModelDiscoveryEngine()

