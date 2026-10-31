import asyncio
import hashlib
import logging
import re
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


class ProviderAuthError(Exception):
    """Credential rejected by the provider (401/403/invalid key). Not retryable as-is."""

    def __init__(
        self,
        message: str = "Provider authentication failed.",
        error_type: str = "authentication_error",
    ):
        super().__init__(message)
        self.error_type = error_type


class ProviderBusyError(Exception):
    """Provider temporarily unable to validate (429/503/timeout/network). Retryable."""

    def __init__(
        self,
        message: str = "Provider is temporarily unavailable.",
        error_type: str = "provider_unavailable",
    ):
        super().__init__(message)
        self.error_type = error_type


class ProviderUnavailableError(Exception):
    """Provider returned no usable data for a non-auth, non-busy reason."""

    def __init__(
        self,
        message: str = "Provider returned no usable models.",
        error_type: str = "provider_unavailable",
    ):
        super().__init__(message)
        self.error_type = error_type


class ProviderConfigError(Exception):
    """Revora-side configuration problem (unknown provider). Not retryable."""

    def __init__(
        self,
        message: str = "Provider is not configured correctly.",
        error_type: str = "configuration_error",
    ):
        super().__init__(message)
        self.error_type = error_type


_AUTH_SIGNALS: tuple[str, ...] = (
    "invalid_api_key",
    "invalid api key",
    "incorrect api key",
    "invalid_api_key_provided",
    "401",
    "403",
    "unauthorized",
    "forbidden",
    "permission",
    "access denied",
    "authentication",
    "invalid x-api-key",
    "invalid key",
)

_BUSY_SIGNALS: tuple[str, ...] = (
    "429",
    "rate_limit",
    "rate limit",
    "rate-limit",
    "quota",
    "quota_exceeded",
    "insufficient_quota",
    "503",
    "502",
    "504",
    "service_unavailable",
    "service unavailable",
    "temporarily unavailable",
    "timeout",
    "timed out",
    "deadline exceeded",
    "connection reset",
    "connection error",
    "network",
    "server error",
    "internal server error",
    "overloaded",
    "try again",
)

# Signals for an exhausted provider balance (notably OpenRouter HTTP 402).
# Never an auth verdict and never a soft success: the key is valid but cannot
# pay for completions. Kept separate from _BUSY_SIGNALS so the outcome maps
# to its own actionable error_type instead of generic "unavailable".
_CREDIT_EXHAUSTED_SIGNALS: tuple[str, ...] = (
    "402",
    "payment required",
    "insufficient credit",
    "insufficient_credit",
    "insufficient funds",
    "out of credits",
    "no credits",
)

# Other HTTP 4xx codes that are neither auth, rate-limit, timeout, nor
# not-found signals. Only applied to OpenRouter (see verify_model_quota_detailed);
# every other provider keeps the legacy retain-on-unknown behaviour.
_UNKNOWN_CLIENT_ERROR_RE = re.compile(r"\b(400|405|409|410|413|422|451)\b")
_UNKNOWN_CLIENT_ERROR_PHRASES: tuple[str, ...] = (
    "bad request",
    "no endpoints",
)


def classify_provider_error(error: Exception) -> tuple[str, str, type]:
    """Map a raw provider exception to (error_type, safe_message, exception_class).

    Never includes raw provider output in the safe message.
    """
    raw = str(error).lower()
    if any(sig in raw for sig in _AUTH_SIGNALS):
        if "403" in raw or "forbidden" in raw or "permission" in raw:
            return (
                "authorization_error",
                "Provider authorization failed. Check key permissions.",
                ProviderAuthError,
            )
        return ("invalid_key", "Invalid API key.", ProviderAuthError)
    if any(sig in raw for sig in _CREDIT_EXHAUSTED_SIGNALS):
        return (
            "insufficient_credits",
            "The provider key has insufficient credits.",
            ProviderBusyError,
        )
    if any(sig in raw for sig in _BUSY_SIGNALS):
        if "429" in raw or "rate" in raw:
            return (
                "rate_limited",
                "Rate limit reached. Try again later.",
                ProviderBusyError,
            )
        if "quota" in raw:
            return (
                "quota_exceeded",
                "Provider quota reached. Try again later.",
                ProviderBusyError,
            )
        if "timeout" in raw or "timed out" in raw or "deadline" in raw:
            return ("timeout", "Validation timed out.", ProviderBusyError)
        return (
            "provider_unavailable",
            "Provider is temporarily unavailable.",
            ProviderBusyError,
        )
    return (
        "provider_unavailable",
        "Provider is temporarily unavailable.",
        ProviderUnavailableError,
    )


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
        "ollama": "ollama",
        "ollama_cloud": "openai",
        "cohere": "cohere",
        "mistral": "mistral",
        "nvidia": "nvidia_nim",
    }

    # Providers that borrow another provider's LiteLLM prefix and therefore
    # need an explicit api_base on EVERY litellm call (model list AND quota
    # smoke tests). Missing the base on any call silently routes to the
    # borrowed provider's default endpoint (e.g. api.openai.com), whose 401
    # then misreports a valid credential as invalid.
    PROVIDER_API_BASES: ClassVar[dict[str, str]] = {
        "ollama_cloud": "https://ollama.com/v1",
    }

    # OpenRouter-scoped validation bounds. OpenRouter's catalogue is ~300
    # models (vs ~20-30 for NVIDIA/Gemini); smoke-testing all of them fans out
    # hundreds of paid 1-token completions, draws 429s, and blows the 22s
    # per-key validation budget — which surfaced as perpetual TEST BUSY.
    # Other providers are untouched by these bounds.
    OPENROUTER_KEY_ENDPOINT: ClassVar[str] = "https://openrouter.ai/api/v1/key"
    OPENROUTER_KEY_TIMEOUT_SECONDS: ClassVar[float] = 10.0
    OPENROUTER_MODELS_ENDPOINT: ClassVar[str] = "https://openrouter.ai/api/v1/models"
    OPENROUTER_MODELS_TIMEOUT_SECONDS: ClassVar[float] = 10.0
    OPENROUTER_SMOKE_SAMPLE_SIZE: ClassVar[int] = 8
    OPENROUTER_SMOKE_CONCURRENCY: ClassVar[int] = 4

    # Terms indicating a model is not a chat model
    NON_CHAT_EXCLUSIONS: ClassVar[list[str]] = [
        "dall-e",
        "whisper",
        "embedding",
        "embed",
        "tts",
        "veo",
        "imagen",
        "lyria",
        "moderation",
        "speech",
        "audio",
        "video",
        "clip",
        "rerank",
        "image-generation",
        "image-preview",
        "1024-x",
        "1536-x",
        "512-x",
        "learnlm",
        "aqa",
        "bison",
        "chat-bison",
        "text-bison",
        "gecko",
        "reward",
        "guardrail",
        "bge-",
        "deplot",
        "diffusion",
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
        "gemini-2.0",
        "gemini-2.5",
        "gemini-2.0-flash",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.0-flash-lite",
        "gemini-2.5-flash-lite",
    ]

    # Groq-specific non-chat families. Groq's Models API
    # (GET https://api.groq.com/openai/v1/models) returns every active
    # model including audio, guard, and agentic-system models, and exposes
    # no modality field — so these are excluded by ID terms. Revora's
    # code-review pipeline requires chat completions.
    GROQ_NON_CHAT_TERMS: ClassVar[list[str]] = [
        "whisper",
        "tts",
        "prompt-guard",
        "llama-guard",
        "embed",
        "playai",
        "orpheus",
        "compound",
    ]

    # Groq model IDs retired by Groq for free/developer-tier usage.
    # Source of truth: https://console.groq.com/docs/deprecations
    # (verified 2026-10-05; refresh when Groq announces new waves —
    # roughly monthly, ~30 days notice by email + deprecations page).
    GROQ_DEPRECATED_IDS: ClassVar[frozenset] = frozenset(
        {
            "llama-3.1-8b-instant",
            "llama-3.3-70b-versatile",
            "qwen/qwen3-32b",
            "meta-llama/llama-4-scout-17b-16e-instruct",
            "meta-llama/llama-4-maverick-17b-128e-instruct",
            "meta-llama/llama-guard-4-12b",
            "moonshotai/kimi-k2-instruct-0905",
            "groq/compound",
            "groq/compound-mini",
        }
    )

    # Curated Groq model metadata supplementing litellm.model_cost.
    # Pricing: USD per 1M tokens (input/output) from
    # https://console.groq.com/docs/models (verified 2026-10-05).
    # Converted to per-token rates in _enrich_model. Only models with
    # officially published specs are listed here; unknown IDs fall back
    # to litellm.model_cost. Free-vs-paid: Groq bills per token on every
    # model (free/developer is an account rate-limit tier, not a
    # per-model attribute), so no model is marked free — see plan §8.
    GROQ_MODEL_METADATA: ClassVar[dict[str, dict[str, object]]] = {
        "openai/gpt-oss-20b": {
            "context_window": 131072,
            "max_completion_tokens": 65536,
            "input_per_1m": 0.075,
            "output_per_1m": 0.30,
            "supports_function_calling": True,
            "supports_reasoning": True,
        },
        "openai/gpt-oss-120b": {
            "context_window": 131072,
            "max_completion_tokens": 65536,
            "input_per_1m": 0.15,
            "output_per_1m": 0.60,
            "supports_function_calling": True,
            "supports_reasoning": True,
        },
        "openai/gpt-oss-safeguard-20b": {
            "context_window": 131072,
            "max_completion_tokens": 65536,
            "input_per_1m": 0.075,
            "output_per_1m": 0.30,
            "supports_function_calling": True,
            "supports_reasoning": True,
            "preview": True,
        },
    }

    DEPRECATED_TERMS: ClassVar[list[str]] = [
        "-001",
        "-0314",
        "-0613",
        "legacy",
        "deprecated",
    ]
    PREVIEW_TERMS: ClassVar[list[str]] = [
        "preview",
        "exp-",
        "experimental",
        "rc",
        "alpha",
        "beta",
    ]
    ENTERPRISE_TERMS: ClassVar[list[str]] = ["enterprise", "provisioned"]

    @classmethod
    async def _verify_openrouter_key(cls, raw_key: str) -> bool:
        """Fail-fast OpenRouter credential check via the documented key endpoint.

        GET https://openrouter.ai/api/v1/key returns 200 for a valid key
        (with quota/usage evidence) and 401 otherwise. Free, non-generative —
        no completion calls are spent here.

        Returns True when the key reports an explicitly exhausted paid-credit
        limit. This is evidence only — it never becomes a verdict here, so a
        low or zero paid balance can never block free-model validation or
        invalidate the key. Free-tier keys are never reported as exhausted:
        paid balance is irrelevant to free models.

        Fail-safe direction: only an explicit 401/403 becomes an auth verdict.
        Every other unexpected outcome stays busy/unavailable so a valid stored
        key is never invalidated by an endpoint hiccup. Raises:
            ProviderAuthError: 401 invalid key / 403 forbidden.
            ProviderBusyError: 429, timeout, 5xx, transport failure.
            ProviderUnavailableError: any other unexpected status.
        """
        import httpx

        headers = {"Authorization": f"Bearer {raw_key}"} if raw_key else {}
        try:
            async with httpx.AsyncClient(
                timeout=cls.OPENROUTER_KEY_TIMEOUT_SECONDS
            ) as client:
                resp = await client.get(cls.OPENROUTER_KEY_ENDPOINT, headers=headers)
        except Exception as e:
            logger.warning(
                "OpenRouter key verification request failed: %s", type(e).__name__
            )
            lowered = str(e).lower()
            if "429" in lowered or "rate" in lowered:
                raise ProviderBusyError(
                    "Provider is temporarily unavailable.", error_type="rate_limited"
                )
            if "timeout" in lowered or "timed out" in lowered or "deadline" in lowered:
                raise ProviderBusyError(
                    "Provider is temporarily unavailable.", error_type="timeout"
                )
            raise ProviderBusyError("Provider is temporarily unavailable.")

        if resp.status_code == 200:
            try:
                data = resp.json().get("data", {}) or {}
            except Exception:
                return False  # Key accepted; body unreadable — do not fail validation.
            limit = data.get("limit")
            remaining = data.get("limit_remaining")
            if (
                limit is not None
                and remaining is not None
                and not data.get("is_free_tier")
            ):
                try:
                    return float(remaining) <= 0
                except (TypeError, ValueError):
                    pass
            return False
        if resp.status_code == 401:
            raise ProviderAuthError("Invalid API key.", error_type="invalid_key")
        if resp.status_code == 403:
            raise ProviderAuthError(
                "Provider authentication failed.", error_type="authorization_error"
            )
        if resp.status_code == 429:
            raise ProviderBusyError(
                "Provider is temporarily unavailable.", error_type="rate_limited"
            )
        if resp.status_code in (502, 503, 504):
            raise ProviderBusyError("Provider is temporarily unavailable.")
        raise ProviderUnavailableError("Provider is temporarily unavailable.")

    @classmethod
    def _is_openrouter_free_model(cls, entry: dict) -> bool:
        """True when a /models catalogue entry is an eligible free model.

        Mirrors the discovery adapter predicate: an explicit ``:free``
        variant ID, or zero prompt *and* completion pricing. OpenRouter-only;
        never consulted for other providers.
        """
        model_id = entry.get("id", "") or ""
        if isinstance(model_id, str) and model_id.endswith(":free"):
            return True
        pricing = entry.get("pricing", {}) or {}
        try:
            return (
                float(pricing.get("prompt", 1)) == 0
                and float(pricing.get("completion", 1)) == 0
            )
        except (TypeError, ValueError):
            return False

    @classmethod
    async def get_available_models(
        cls, provider: str, raw_key: str, force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        """
        Get enriched model metadata for a specific provider and API key.
        Uses caching to prevent excessive API calls.

        Raises:
            ProviderConfigError: unknown provider (Revora-side config issue).
            ProviderAuthError: credential rejected (401/403/invalid key).
            ProviderBusyError: transient condition (429/quota/5xx/timeout/network).
            ProviderUnavailableError: no usable models for another reason.

        Only successful, non-empty discoveries are cached. Failures are never
        cached as success. Pass force_refresh=True for explicit user-triggered
        revalidation (e.g. Validate All) to bypass a stale success cache.
        """
        litellm_prov = cls.LITELLM_PROVIDER_MAP.get(provider.lower())
        if not litellm_prov:
            raise ProviderConfigError(
                f"Unsupported provider: {provider}.",
                error_type="unknown_provider",
            )

        # Check cache using hashed key (skipped on explicit refresh)
        cache_key = f"{litellm_prov}:{_hash_api_key(raw_key)}"
        cached = _MODEL_CACHE.get(cache_key)
        now = datetime.now(UTC)

        if not force_refresh and cached and (now - cached["timestamp"]) < CACHE_TTL:
            return cached["models"]

        paid_balance_exhausted = False
        if provider.lower() == "openrouter":
            # Fail fast on rejected credentials before spending any
            # completion calls. Transient outcomes preserve validity (busy),
            # so this never invalidates a stored key on a hiccup. An
            # exhausted paid balance is evidence only — it must never block
            # free-model validation.
            paid_balance_exhausted = await cls._verify_openrouter_key(raw_key)

        live_models: list[str] = []
        openrouter_free_ids: set[str] = set()
        try:
            if litellm_prov == "nvidia_nim":
                try:
                    import httpx

                    headers = {"Authorization": f"Bearer {raw_key}"} if raw_key else {}
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        resp = await client.get(
                            "https://integrate.api.nvidia.com/v1/models",
                            headers=headers,
                        )
                        if resp.status_code == 200:
                            data = resp.json().get("data", [])
                            live_models = [
                                m["id"]
                                for m in data
                                if isinstance(m, dict) and "id" in m
                            ]
                        elif resp.status_code in (401, 403):
                            # Never fall back on auth failures: the credential
                            # itself was rejected, not the model catalogue.
                            raise ProviderAuthError(
                                "Provider authentication failed.",
                                error_type=(
                                    "authorization_error"
                                    if resp.status_code == 403
                                    else "invalid_key"
                                ),
                            )
                        else:
                            raise ProviderUnavailableError(
                                "Provider is temporarily unavailable."
                            )
                except (ProviderAuthError, ProviderUnavailableError):
                    raise
                except Exception as e:
                    logger.warning(
                        f"Direct NVIDIA API model fetch failed: {type(e).__name__}"
                    )
                    raise ProviderBusyError("Provider is temporarily unavailable.")

                if not live_models:
                    # Empty catalogue without an auth signal is transient —
                    # report busy rather than synthesising success from
                    # hardcoded data or claiming the key is invalid.
                    raise ProviderUnavailableError(
                        "Provider returned no usable models."
                    )
            elif provider.lower() == "cohere":
                try:
                    import httpx

                    headers = {"Authorization": f"Bearer {raw_key}"} if raw_key else {}
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        resp = await client.get(
                            "https://api.cohere.com/v2/models",
                            headers=headers,
                        )
                        if resp.status_code == 200:
                            data = resp.json().get("models", [])
                            live_models = [
                                m["name"]
                                for m in data
                                if isinstance(m, dict)
                                and "name" in m
                                and "chat" in m.get("endpoints", [])
                            ]
                        elif resp.status_code in (401, 403):
                            raise ProviderAuthError(
                                "Provider authentication failed.",
                                error_type=(
                                    "authorization_error"
                                    if resp.status_code == 403
                                    else "invalid_key"
                                ),
                            )
                        else:
                            raise ProviderUnavailableError(
                                "Provider is temporarily unavailable."
                            )
                except (ProviderAuthError, ProviderUnavailableError):
                    raise
                except Exception as e:
                    logger.warning(
                        f"Direct Cohere API model fetch failed: {type(e).__name__}"
                    )
                    raise ProviderBusyError("Provider is temporarily unavailable.")
                if not live_models:
                    raise ProviderUnavailableError(
                        "Provider returned no usable models."
                    )
            elif provider.lower() == "mistral":
                # Direct catalogue fetch. Query Mistral's /v1/models
                # endpoint with Bearer auth to get live chat models.
                try:
                    import httpx

                    headers = {"Authorization": f"Bearer {raw_key}"} if raw_key else {}
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        resp = await client.get(
                            "https://api.mistral.ai/v1/models",
                            headers=headers,
                        )
                        if resp.status_code == 200:
                            data = resp.json().get("data", [])
                            live_models = [
                                m["id"]
                                for m in data
                                if isinstance(m, dict)
                                and "id" in m
                                and not any(
                                    term in m["id"].lower()
                                    for term in ("embed", "embedding", "moderation")
                                )
                            ]
                        elif resp.status_code in (401, 403):
                            raise ProviderAuthError(
                                "Provider authentication failed.",
                                error_type=(
                                    "authorization_error"
                                    if resp.status_code == 403
                                    else "invalid_key"
                                ),
                            )
                        else:
                            raise ProviderUnavailableError(
                                "Provider is temporarily unavailable."
                            )
                except (ProviderAuthError, ProviderUnavailableError):
                    raise
                except Exception as e:
                    logger.warning(
                        f"Direct Mistral API model fetch failed: {type(e).__name__}"
                    )
                    raise ProviderBusyError("Provider is temporarily unavailable.")
                if not live_models:
                    raise ProviderUnavailableError(
                        "Provider returned no usable models."
                    )
            elif provider.lower() == "openrouter":
                # Direct catalogue fetch. The installed LiteLLM cannot serve
                # OpenRouter here (provider config unresolvable, static
                # fallback list empty), so litellm.get_valid_models() always
                # yields [] for it. Query the public models endpoint directly
                # instead — same pattern as the NVIDIA/Cohere branches above.
                # The credential itself was already verified by
                # _verify_openrouter_key (/models is public and accepts any
                # bearer), so only explicit 401/403 become auth verdicts;
                # everything else stays busy/unavailable and never invalidates.
                try:
                    import httpx

                    headers = {"Authorization": f"Bearer {raw_key}"} if raw_key else {}
                    async with httpx.AsyncClient(
                        timeout=cls.OPENROUTER_MODELS_TIMEOUT_SECONDS
                    ) as client:
                        resp = await client.get(
                            cls.OPENROUTER_MODELS_ENDPOINT,
                            headers=headers,
                        )
                        if resp.status_code == 200:
                            try:
                                data = resp.json().get("data", []) or []
                            except Exception:
                                data = []
                            live_models = [
                                m["id"]
                                for m in data
                                if isinstance(m, dict) and "id" in m
                            ]
                            # Record eligible free models (zero pricing or an
                            # explicit :free variant, e.g. cohere/north-mini-code:free)
                            # so validation smokes free models first and never
                            # spends paid completions on a free-tier key.
                            openrouter_free_ids.update(
                                m["id"]
                                for m in data
                                if isinstance(m, dict)
                                and "id" in m
                                and cls._is_openrouter_free_model(m)
                            )
                        elif resp.status_code == 401:
                            raise ProviderAuthError(
                                "Invalid API key.", error_type="invalid_key"
                            )
                        elif resp.status_code == 403:
                            raise ProviderAuthError(
                                "Provider authentication failed.",
                                error_type="authorization_error",
                            )
                        elif resp.status_code == 429:
                            raise ProviderBusyError(
                                "Provider is temporarily unavailable.",
                                error_type="rate_limited",
                            )
                        elif resp.status_code in (502, 503, 504):
                            raise ProviderBusyError(
                                "Provider is temporarily unavailable."
                            )
                        else:
                            raise ProviderUnavailableError(
                                "Provider is temporarily unavailable."
                            )
                except (ProviderAuthError, ProviderBusyError, ProviderUnavailableError):
                    raise
                except Exception as e:
                    logger.warning(
                        f"Direct OpenRouter API model fetch failed: {type(e).__name__}"
                    )
                    lowered = str(e).lower()
                    if "429" in lowered or "rate" in lowered:
                        raise ProviderBusyError(
                            "Provider is temporarily unavailable.",
                            error_type="rate_limited",
                        )
                    if (
                        "timeout" in lowered
                        or "timed out" in lowered
                        or "deadline" in lowered
                    ):
                        raise ProviderBusyError(
                            "Provider is temporarily unavailable.", error_type="timeout"
                        )
                    raise ProviderBusyError("Provider is temporarily unavailable.")
                if not live_models:
                    raise ProviderUnavailableError(
                        "Provider returned no usable models."
                    )
            else:
                api_base = cls.PROVIDER_API_BASES.get(provider.lower())

                # Query the provider's actual API endpoint
                try:
                    live_models = await asyncio.to_thread(
                        litellm.get_valid_models,
                        check_provider_endpoint=True,
                        custom_llm_provider=litellm_prov,
                        api_key=raw_key,
                        api_base=api_base,
                    )
                except Exception as e:
                    _, _, exc_cls = classify_provider_error(e)
                    logger.warning(
                        f"Live model fetch failed for provider '{provider}': {type(e).__name__}"
                    )
                    if exc_cls is ProviderAuthError:
                        error_type, _, _ = classify_provider_error(e)
                        raise ProviderAuthError(
                            "Invalid API key."
                            if error_type == "invalid_key"
                            else "Provider authentication failed.",
                            error_type=error_type,
                        )
                    if exc_cls is ProviderBusyError:
                        error_type, _, _ = classify_provider_error(e)
                        raise ProviderBusyError(
                            "Provider is temporarily unavailable.",
                            error_type=error_type,
                        )
                    raise ProviderUnavailableError(
                        "Provider is temporarily unavailable."
                    )
        except (
            ProviderAuthError,
            ProviderBusyError,
            ProviderUnavailableError,
            ProviderConfigError,
        ):
            # Never cache failures. Propagate typed errors so callers can
            # distinguish invalid vs busy vs unavailable.
            raise

        if not live_models:
            raise ProviderUnavailableError("Provider returned no usable models.")

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

            # Exclude Groq non-chat families (audio/guard/agentic). The
            # Groq Models API exposes no modality field, so filter by ID.
            if provider.lower() == "groq" and any(
                ex in m_lower for ex in cls.GROQ_NON_CHAT_TERMS
            ):
                logger.info(f"Skipping non-chat Groq model: {model_name}")
                continue

            canonical_model = cls._enrich_model(model_name, provider)
            enriched_models.append(canonical_model)

        if not enriched_models:
            # Catalogue contained no usable chat models. The credential was
            # accepted by the model-list endpoint, so this is not an auth
            # failure — report unavailable rather than invalid.
            raise ProviderUnavailableError("Provider returned no usable models.")

        # Run concurrent quota checks for all discovered models.
        # Auth rejections observed here (model list accepted the key but
        # completions reject it, e.g. entitlement issues) must surface as
        # auth failures, not silent empty results.
        # Providers borrowing another provider's LiteLLM prefix (see
        # PROVIDER_API_BASES) must pass their api_base here too, or the
        # smoke test routes to the wrong endpoint and a valid key fails.
        quota_api_base = cls.PROVIDER_API_BASES.get(provider.lower())
        smoke_auth_failures = 0
        smoke_credit_failures: list[str] = []

        # OpenRouter only: smoke eligible free models first with limited
        # concurrency. Every other provider keeps the legacy unbounded
        # behaviour. Non-sampled OpenRouter models keep their default
        # accessible=True (listed, quota unverified) — the credential
        # verdict itself rests on the /key pre-check plus the sample.
        # When the catalogue holds no free models, smoke nothing at all:
        # key validation must never spend paid completion calls on a
        # free-tier key.
        smoke_targets = enriched_models
        smoke_semaphore: asyncio.Semaphore | None = None
        smoke_sink: list[str] | None = None
        if provider.lower() == "openrouter":
            free_targets = [
                m
                for m in enriched_models
                if m.canonical_model_name in openrouter_free_ids
            ]
            smoke_targets = free_targets[: cls.OPENROUTER_SMOKE_SAMPLE_SIZE]
            smoke_semaphore = asyncio.Semaphore(cls.OPENROUTER_SMOKE_CONCURRENCY)
            smoke_sink = smoke_credit_failures

        async def verify_and_update(c_model: CanonicalModel):
            nonlocal smoke_auth_failures
            if smoke_semaphore is not None:
                async with smoke_semaphore:
                    accessible, saw_auth = await cls.verify_model_quota_detailed(
                        c_model,
                        raw_key,
                        api_base=quota_api_base,
                        credit_sink=smoke_sink,
                    )
            else:
                accessible, saw_auth = await cls.verify_model_quota_detailed(
                    c_model, raw_key, api_base=quota_api_base
                )
            if not accessible and saw_auth:
                smoke_auth_failures += 1
            c_model.accessible = accessible
            canonical_registry.register(c_model)
            return c_model.model_dump()

        validated_models = await asyncio.gather(
            *(verify_and_update(m) for m in smoke_targets)
        )

        # Verdict rests on the sampled smokes only: auth rejections invalidate,
        # exhausted credit maps to insufficient_credits, anything else empty
        # maps to unavailable. The unsmoked remainder is appended afterwards
        # as listed-but-quota-unverified so the model picker keeps the full
        # catalogue; it never flips the verdict.
        # OpenRouter-only additions: an exhausted paid balance (pre-check
        # evidence, non-free-tier keys) also maps to insufficient_credits —
        # but only after free-model smokes were attempted. A valid key with
        # no verifiable free model maps to no_free_model (busy, never
        # invalid, never "add credits").
        sampled_models = [m for m in validated_models if m["accessible"]]

        if not sampled_models:
            if smoke_auth_failures:
                raise ProviderAuthError("Invalid API key.", error_type="invalid_key")
            if smoke_credit_failures:
                raise ProviderBusyError(
                    "The provider key has insufficient credits.",
                    error_type="insufficient_credits",
                )
            if provider.lower() == "openrouter" and paid_balance_exhausted:
                raise ProviderBusyError(
                    "The provider key has insufficient credits.",
                    error_type="insufficient_credits",
                )
            if provider.lower() == "openrouter":
                raise ProviderBusyError(
                    "No free model could be verified with this key.",
                    error_type="no_free_model",
                )
            raise ProviderUnavailableError("Provider returned no usable models.")

        final_models = list(sampled_models)
        if provider.lower() == "openrouter" and len(smoke_targets) < len(
            enriched_models
        ):
            smoked_names = {m.canonical_model_name for m in smoke_targets}
            for c_model in enriched_models:
                if c_model.canonical_model_name not in smoked_names:
                    canonical_registry.register(c_model)
                    final_models.append(c_model.model_dump())

        # Sort so recommended models appear at the top
        def get_model_priority(m: dict) -> int:
            name = m.get("canonical_model_name", "")
            if name in cls.RECOMMENDED_MODELS:
                return cls.RECOMMENDED_MODELS.index(name)
            return 999

        final_models.sort(key=get_model_priority)

        # Cache only successful, non-empty discoveries. Failures, busy
        # states, and empty results are never cached as success.
        _MODEL_CACHE[cache_key] = {"timestamp": now, "models": final_models}

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
        elif provider_lower == "openrouter" and not model_name.startswith(
            "openrouter/"
        ):
            litellm_model_name = f"openrouter/{canonical_model_name}"
        elif provider_lower == "ollama" and not model_name.startswith("ollama/"):
            litellm_model_name = f"ollama/{canonical_model_name}"
        elif provider_lower == "ollama_cloud" and not model_name.startswith("openai/"):
            litellm_model_name = f"openai/{canonical_model_name}"
        elif provider_lower == "cohere" and not model_name.startswith("cohere_chat/"):
            litellm_model_name = f"cohere_chat/{canonical_model_name}"
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
        input_cost = (
            info.get("input_cost_per_token")
            or info.get("input_cost_per_prompt_token")
            or 0.0
        )
        output_cost = (
            info.get("output_cost_per_token")
            or info.get("output_cost_per_completion_token")
            or 0.0
        )

        supports_vision = info.get("supports_vision", False)
        supports_function_calling = info.get("supports_function_calling", False)
        supports_streaming = info.get("supports_streaming", True)
        supports_reasoning = "reasoning" in m_lower or "o1" in m_lower

        # Groq overlay: official per-model metadata supplements litellm.
        # Groq retires models frequently; deprecated IDs are forced
        # deprecated here so validate_model_access rejects them and the
        # repository picker filters them, per existing convention.
        if provider_lower == "groq":
            if (
                canonical_model_name in cls.GROQ_DEPRECATED_IDS
                or model_name in cls.GROQ_DEPRECATED_IDS
            ):
                is_deprecated = True
            meta = cls.GROQ_MODEL_METADATA.get(
                canonical_model_name, cls.GROQ_MODEL_METADATA.get(model_name, {})
            )
            if meta:
                if meta.get("context_window"):
                    context_window = meta["context_window"]
                if meta.get("input_per_1m") is not None:
                    input_cost = float(meta["input_per_1m"]) / 1_000_000
                if meta.get("output_per_1m") is not None:
                    output_cost = float(meta["output_per_1m"]) / 1_000_000
                if meta.get("supports_function_calling"):
                    supports_function_calling = True
                if meta.get("supports_reasoning"):
                    supports_reasoning = True
                if meta.get("preview"):
                    is_preview = True

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
            supports_reasoning=supports_reasoning,
            status=status,
            validation_timestamp=datetime.now(UTC).isoformat(),
        )

    @classmethod
    async def verify_model_quota(
        cls, canonical_model: CanonicalModel, raw_key: str, api_base: str | None = None
    ) -> bool:
        """
        Executes a 1-token smoke test to verify if the API key has quota for this model.

        Returns True if the model is usable, False if it is not (unsupported
        model, or the credential was rejected with 401/403).

        Transient conditions (429/503/timeout) retain the model as accessible
        so a busy provider is not misreported as an invalid credential.

        api_base must be supplied for providers that borrow another
        provider's LiteLLM prefix (see PROVIDER_API_BASES); otherwise the
        smoke test routes to the wrong endpoint.
        """
        accessible, _ = await cls.verify_model_quota_detailed(
            canonical_model, raw_key, api_base=api_base
        )
        return accessible

    @classmethod
    async def verify_model_quota_detailed(
        cls,
        canonical_model: CanonicalModel,
        raw_key: str,
        api_base: str | None = None,
        credit_sink: list[str] | None = None,
    ) -> tuple[bool, bool]:
        """
        Smoke-test variant returning (accessible, saw_auth_failure).

        Classification:
          success                    -> (True, False)
          401/403/invalid-key        -> (False, True)  -- never soft-success
          402/exhausted credit       -> (False, False) -- never soft-success;
             recorded into credit_sink (when provided) so callers can report
             insufficient_credits instead of generic unavailable.
          404/not-found/unsupported  -> (False, False)
          OpenRouter unknown 4xx    -> (False, False) -- OpenRouter only; all
             other providers retain the legacy soft-success for these.
          429/503/timeout/transient  -> (True, False)  -- retain, do not invalidate

        api_base must be supplied for providers borrowing another
        provider's prefix (see PROVIDER_API_BASES).
        """
        try:
            await asyncio.wait_for(
                asyncio.to_thread(
                    litellm.completion,
                    model=canonical_model.litellm_model_name,
                    messages=[{"role": "user", "content": "hi"}],
                    api_key=raw_key,
                    api_base=api_base,
                    max_tokens=1,
                    drop_params=True,
                ),
                timeout=5,
            )
            return True, False
        except Exception as e:
            error_str = str(e).lower()
            if any(
                sig in error_str
                for sig in (
                    "invalid_api_key",
                    "invalid api key",
                    "incorrect api key",
                    "401",
                    "unauthorized",
                )
            ) or (
                ("403" in error_str or "forbidden" in error_str)
                and "rate" not in error_str
            ):
                # Authentication/authorization rejection: the credential (or
                # its entitlement for this model) was refused. Must NOT be
                # treated as soft success — that would mark invalid keys valid.
                logger.warning(
                    f"Smoke test auth failure for {canonical_model.canonical_model_name}: {type(e).__name__}"
                )
                return False, True
            if any(sig in error_str for sig in _CREDIT_EXHAUSTED_SIGNALS):
                # Exhausted balance (notably OpenRouter 402): the key is
                # valid but cannot pay. Must NOT be soft-success (that would
                # report broke keys as accessible) and must NOT read as auth.
                logger.warning(
                    f"Smoke test credit failure for {canonical_model.canonical_model_name}: {type(e).__name__}"
                )
                if credit_sink is not None:
                    credit_sink.append(canonical_model.canonical_model_name)
                return False, False
            if (
                "404" in error_str
                or "not found" in error_str
                or "no endpoints" in error_str
                or "unsupported" in error_str
            ):
                logger.warning(
                    f"Model {canonical_model.canonical_model_name} not supported: {type(e).__name__}"
                )
                return False, False
            if (
                getattr(canonical_model, "provider", "").lower() == "openrouter"
                and (
                    _UNKNOWN_CLIENT_ERROR_RE.search(error_str)
                    or any(sig in error_str for sig in _UNKNOWN_CLIENT_ERROR_PHRASES)
                )
                and not any(
                    sig in error_str
                    for sig in (
                        "429",
                        "rate",
                        "408",
                        "timeout",
                        "timed out",
                        "deadline",
                    )
                )
            ):
                # OpenRouter-only: an unrecognised client error is a per-model
                # exclusion, never a soft success. Other providers keep the
                # legacy retain behaviour below (unchanged).
                logger.warning(
                    f"Model {canonical_model.canonical_model_name} client error, excluding: {type(e).__name__}"
                )
                return False, False

            # Transient 429/timeout/server error: retain model as accessible
            # so a busy provider is not misreported as an invalid credential.
            logger.info(
                f"Smoke test soft failure for {canonical_model.canonical_model_name}: {type(e).__name__}"
            )
            return True, False

    @classmethod
    async def validate_model_access(
        cls, provider: str, model_name: str, raw_key: str
    ) -> bool:
        """
        Validates if a specific model is accessible with the given key.
        Returns False when the provider cannot confirm access (auth failure,
        busy provider, or unknown model) instead of raising.
        """
        try:
            available = await cls.get_available_models(provider, raw_key)
        except Exception:
            return False
        for m in available:
            if model_name in [
                m["canonical_model_name"],
                m["litellm_model_name"],
                m["provider_model_name"],
                m.get("model_name", ""),
            ]:
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


async def warm_model_cache(provider: str, raw_key: str) -> None:
    """Fire-and-forget cache warmup for background tasks.

    Discovery raises typed errors (auth/busy/unavailable) instead of
    returning []; background warmups must never propagate those — a failed
    warmup simply leaves the cache empty for the next live lookup.
    """
    try:
        await model_discovery_engine.get_available_models(provider, raw_key)
    except Exception as e:
        logger.debug(
            "Background model cache warmup skipped for '%s': %s",
            provider,
            type(e).__name__,
        )
