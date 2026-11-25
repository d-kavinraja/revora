"""LiteLLM wrapper for LLM API calls.

Provides async interface to LLM providers via LiteLLM,
with user API key resolution from database.

BYOK Principle: This service uses EXACTLY the key and model it is given.
No fallback, no key cycling, no provider switching.
"""

import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from litellm import acompletion

from app.ai import kllm_client
from app.ai.model_registry import canonical_registry
from app.core.config import settings
from app.core.constants import LLM_DEFAULT_TIMEOUT
from app.db.session import AsyncSessionLocal
from app.services.api_key_service import api_key_service

logger = logging.getLogger(__name__)


class ManagedModelError(RuntimeError):
    """Managed-provider failure that keeps its structured lifecycle reason."""

    def __init__(self, message: str, reason_code: str):
        super().__init__(message)
        self.message = message
        self.reason_code = reason_code or "kllm_error"


class LLMService:
    """Async LLM service — single provider, single key, single model per call."""

    async def get_completion(
        self,
        user_id: uuid.UUID,
        provider: str,
        messages: list,
        model: str | None = None,
        api_key_id: str | None = None,
        timeout: int = LLM_DEFAULT_TIMEOUT,
        cancel_check: Callable[[], Awaitable[bool]] | None = None,
    ) -> tuple[str | None, int, int]:
        """Execute exactly one LLM call with the given provider/key/model.

        Args:
            user_id: User UUID for API key lookup.
            provider: LLM provider name (gemini, openai, anthropic, etc.).
            messages: List of message dicts for the LLM.
            model: Model name to use (must be provided).
            api_key_id: Specific API key ID to use (must be provided for MODE 1).
            timeout: Timeout in seconds for the LLM call.

        Returns:
            Tuple of (response_text, input_tokens, output_tokens).

        Raises:
            ValueError: If no valid API key is found.
            RuntimeError: If LLM call fails (exact error surfaced).
        """
        if not model:
            raise ValueError(f"Model must be specified for provider '{provider}'")

        managed = await self._is_managed(provider)
        if managed:
            # Server-owned provider: no user key, and readiness is validated
            # against live kLLM state immediately before the call.
            await self._ensure_managed_ready(model, cancel_check=cancel_check)
            api_key = settings.KLLM_GATEWAY_API_KEY or "sk-kllm-local"
        else:
            api_key = await self._resolve_api_key(user_id, provider, api_key_id)
            if not api_key:
                raise ValueError(
                    f"No valid API key found for provider '{provider}'. "
                    f"Please add an API key in Settings > API Keys."
                )

        model_to_use, _ = self._resolve_model(provider, model)

        display_model = model
        if model_to_use.startswith("nvidia_nim/"):
            display_model = model_to_use[len("nvidia_nim/") :]
        elif model_to_use.startswith("openai/") and (
            provider == "ollama_cloud" or managed
        ):
            display_model = model_to_use[len("openai/") :]

        # Determine custom base URL for cloud providers
        api_base = None
        if managed:
            api_base = f"{settings.KLLM_SERVER_URL.rstrip('/')}/v1"
        elif provider == "ollama_cloud":
            api_base = "https://ollama.com/v1"

        try:
            # Removed asyncio.wait_for to ensure the system waits as long as needed
            # for the AI to complete its response without failing due to artificial limits.
            response = await acompletion(
                model=model_to_use,
                messages=messages,
                api_key=api_key,
                api_base=api_base,
                num_retries=1 if managed else 2,
                timeout=None,  # Disable LiteLLM's internal timeout
            )

            if isinstance(response, dict):
                logger.warning(
                    "litellm returned dict for %s (keys suppressed)", display_model
                )
                raise RuntimeError(  # noqa: TRY004
                    "LLM provider returned an error response for "
                    f"'{display_model}'. Please try again later."
                )

            if (
                response
                and hasattr(response, "choices")
                and response.choices
                and response.choices[0].message
            ):
                content = response.choices[0].message.content
                input_tokens = 0
                output_tokens = 0
                if hasattr(response, "usage") and response.usage:
                    input_tokens = getattr(response.usage, "prompt_tokens", 0) or 0
                    output_tokens = getattr(response.usage, "completion_tokens", 0) or 0
                return content, input_tokens, output_tokens
            return None, 0, 0

        except TimeoutError:
            raise RuntimeError(
                f"LLM network connection to {provider}/{display_model} timed out unexpectedly."
            )
        except Exception as e:
            error_str = str(e).lower()
            if managed:
                raise RuntimeError(self._managed_error_message(e, display_model)) from e
            if (
                "overloaded" in error_str
                or "503" in error_str
                or "busy" in error_str
                or "capacity" in error_str
            ):
                raise RuntimeError(
                    f"Provider server is temporarily overloaded for '{display_model}'. "
                    f"The API is experiencing high traffic. Please try again in a moment."
                ) from e
            elif "429" in error_str or "rate" in error_str or "quota" in error_str:
                raise RuntimeError(
                    f"Rate limit exceeded for model '{display_model}'. "
                    f"Please wait a moment and try again."
                ) from e
            elif "401" in error_str or "unauthorized" in error_str:
                raise RuntimeError(
                    f"Invalid API key for {provider}. "
                    f"Please update your API key in Settings > API Keys."
                ) from e
            elif "403" in error_str or "forbidden" in error_str:
                raise RuntimeError(
                    f"API access denied for model '{display_model}'. "
                    f"Your API key may not have the required permissions."
                ) from e
            elif "404" in error_str or "not found" in error_str:
                raise RuntimeError(
                    f"Model '{display_model}' not found or deprecated by the provider. "
                    f"Please check your provider settings."
                ) from e
            elif (
                "410" in error_str
                or "end of life" in error_str
                or "gone" in error_str
                or "removed" in error_str
            ):
                raise RuntimeError(
                    f"Model '{display_model}' has reached its end of life and is no longer available from the provider. "
                    f"Please select a different model."
                ) from e
            elif "timeout" in error_str:
                raise RuntimeError(
                    f"AI provider timed out for '{display_model}'. "
                    f"Please try again later."
                ) from e
            elif "connection" in error_str or "connect" in error_str:
                raise RuntimeError(
                    f"Unable to connect to AI provider '{provider}'. "
                    f"Please check your network connection."
                ) from e
            else:
                raise RuntimeError(
                    f"AI provider error for '{display_model}'. Please try again later."
                ) from e

    async def _is_managed(self, provider: str) -> bool:
        """True for server-owned providers (kLLM), which never use user keys."""
        try:
            async with AsyncSessionLocal() as db:
                from app.services.provider_registry import provider_registry_service

                row = await provider_registry_service.get_by_identifier(db, provider)
                if row is not None:
                    return bool(row.is_managed)
        except Exception as exc:
            logger.warning("Managed-provider lookup failed: %s", type(exc).__name__)
        return provider.lower() == "kllm"

    def _managed_error_message(self, error: Exception, display_model: str) -> str:
        """Map managed kLLM errors to safe, user-facing messages.

        Never surface raw upstream payloads, account names, URLs, or credentials.
        """
        error_str = str(error).lower()
        if "401" in error_str or "403" in error_str or "unauthorized" in error_str:
            return (
                "kLLM rejected the server credentials. "
                "Check KLLM_GATEWAY_API_KEY in the backend environment."
            )
        if "404" in error_str or "not found" in error_str:
            return (
                f"Model '{display_model}' was not found in kLLM. "
                "Refresh the dashboard and select a loaded model."
            )
        if (
            "overloaded" in error_str
            or "503" in error_str
            or "busy" in error_str
            or "capacity" in error_str
            or "429" in error_str
            or "rate" in error_str
        ):
            return (
                f"kLLM is busy or at capacity for '{display_model}'. "
                "Please try again in a moment."
            )
        if "timeout" in error_str or "timed out" in error_str:
            return f"kLLM timed out while serving '{display_model}'."
        if "connection" in error_str or "connect" in error_str:
            return (
                "Unable to connect to kLLM. Ensure the kLLM relay is "
                "running and KLLM_SERVER_URL is correct."
            )
        return f"kLLM error while serving '{display_model}'. Please try again later."

    async def complete_managed(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 1024,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        timeout: float | None = None,
    ) -> tuple[str, int, int, str | None]:
        """Non-streaming completion via the direct kLLM relay client.

        The kLLM Chat pathway deliberately bypasses LiteLLM: kLLM already
        speaks the OpenAI protocol and LiteLLM rejects relay-supported
        parameters such as ``reasoning_effort`` before any HTTP request.
        The caller must validate readiness with kllm_service.ensure_model_ready()
        immediately before calling; this method never autoloads.
        """
        result = await kllm_client.kllm_chat_client.complete(
            model,
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            timeout=timeout,
        )
        # The provider finish reason is returned, never inferred: the endpoint
        # must not report a clean stop for a length/filter termination.
        return (
            result.content,
            result.prompt_tokens,
            result.completion_tokens,
            getattr(result, "finish_reason", None),
        )

    async def stream_managed_completion(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 1024,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
    ) -> AsyncIterator[kllm_client.ContentDelta | kllm_client.StreamMeta]:
        """Stream normalized kLLM events via the direct relay client.

        Yields ``ContentDelta`` (a ``str`` subclass) for text and ``StreamMeta``
        for presence-gated metadata (usage, timings, neutral status, done).
        Existing string-only consumers keep working unchanged. The caller must
        validate readiness first; this method never autoloads or persists data.
        """
        async for item in kllm_client.kllm_chat_client.stream(
            model,
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
        ):
            yield item

    async def complete_hosted(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 1024,
        temperature: float | None = None,
        timeout: float | None = None,
        context_window: int | None = None,
    ) -> tuple[str, int, int, str | None]:
        """Non-streaming completion via the hosted Ollama client.

        ``model`` is the bare Ollama name (the namespaced hosted key is resolved
        by the caller). The caller must validate readiness with
        hosted_ollama_service.ensure_model_ready() first; this never autoloads.
        """
        from app.ai import hosted_ollama_client

        result = await hosted_ollama_client.hosted_ollama_client.complete(
            model,
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            # Diagnostic only: lets a rejection log compare the prompt size with
            # the runner's real window. Never sent upstream.
            context_window=context_window,
        )
        # Same contract as complete_managed: the provider reason travels with
        # the content instead of being replaced downstream.
        return (
            result.content,
            result.prompt_tokens,
            result.completion_tokens,
            getattr(result, "finish_reason", None),
        )

    async def stream_hosted_completion(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 1024,
        temperature: float | None = None,
        context_window: int | None = None,
    ) -> AsyncIterator[kllm_client.ContentDelta | kllm_client.StreamMeta]:
        """Stream normalized hosted Ollama events as ContentDelta / StreamMeta.

        Reuses the same event types as the kLLM pathway so the SSE contract is
        unchanged. The caller must validate readiness first; this never
        autoloads or persists data.
        """
        from app.ai import hosted_ollama_client

        async for item in hosted_ollama_client.hosted_ollama_client.stream(
            model,
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            # Diagnostic only: see complete_hosted().
            context_window=context_window,
        ):
            yield item

    async def _ensure_managed_ready(
        self,
        model: str,
        *,
        cancel_check: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        """Wait for genuine kLLM readiness before inference.

        A ready model returns immediately. An unloaded model is loaded only
        when the administrator approved that exact model for review-demand
        loading; otherwise this fails without substituting another model.
        The cancellation callback is forwarded into the readiness wait so a
        cancelled review cannot remain parked until the load timeout.
        """
        from app.services import kllm_autoload
        from app.services.kllm_service import KllmError

        try:
            async with AsyncSessionLocal() as db:
                await kllm_autoload.ensure_model_ready_with_autoload(
                    db,
                    model,
                    cancel_check=cancel_check,
                )
        except KllmError as exc:
            raise ManagedModelError(
                exc.message, exc.reason_code or "kllm_error"
            ) from exc

    async def _resolve_api_key(
        self,
        user_id: uuid.UUID,
        provider: str,
        api_key_id: str | None = None,
    ) -> str | None:
        """Resolve API key from database only.

        When api_key_id is provided (MODE 1), ONLY that specific key is used.
        When api_key_id is None (MODE 2), the first valid key for the provider is used.

        No environment variable fallback — env keys are handled by resolve_provider_config().
        """
        try:
            async with AsyncSessionLocal() as db:
                if api_key_id:
                    logger.info(
                        f"Resolving API key by id={api_key_id} for user={user_id}"
                    )
                    from app.core.security import encryption_service

                    try:
                        key_uuid = uuid.UUID(api_key_id)
                    except ValueError:
                        logger.warning(f"Invalid API key ID format: {api_key_id}")
                        return None

                    db_key = await api_key_service.get_by_id(db, key_uuid)
                    if (
                        db_key
                        and db_key.user_id == user_id
                        and db_key.is_valid
                        and db_key.is_enabled
                    ):
                        decrypted = encryption_service.decrypt(db_key.encrypted_key)
                        logger.info(
                            f"Resolved API key by id: {db_key.label} "
                            f"(provider={db_key.provider})"
                        )
                        return decrypted
                    logger.warning(
                        f"API key id={api_key_id} not found or not valid "
                        f"for user={user_id}"
                    )
                    return None
                else:
                    logger.info(
                        f"Resolving API key by provider={provider} for user={user_id}"
                    )
                    all_keys = await api_key_service.get_all_decrypted_keys(
                        db, user_id, provider
                    )
                    if all_keys:
                        key_id, key_value = all_keys[0]
                        logger.info(
                            f"Resolved API key: id={key_id} "
                            f"(provider={provider}, {len(all_keys)} total keys)"
                        )
                        return key_value
                    logger.warning(
                        f"No API key found for provider={provider}, user={user_id}"
                    )
                    return None
        except Exception as e:
            logger.warning(f"Failed to resolve API key from database: {e}")
            return None

    async def get_provider_keys_for_user(
        self,
        user_id: uuid.UUID,
        provider: str,
    ) -> list:
        """Get all decrypted API keys for a provider (MODE 2 provider discovery).

        No environment variable fallback.
        """
        try:
            async with AsyncSessionLocal() as db:
                db_keys = await api_key_service.get_all_decrypted_keys(
                    db, user_id, provider
                )
                if db_keys:
                    return db_keys
        except Exception as e:
            logger.warning(f"Failed to get API keys from database: {e}")
        return []

    def _resolve_model(self, provider: str, model: str):
        """Resolve model name through Canonical Model Registry.

        Args:
            provider: Provider name.
            model: Model name to resolve (must be provided by caller).

        Returns:
            Tuple of (litellm_model_name, canonical_model_or_None)
        """
        if not model:
            raise ValueError(f"Model must be specified for provider '{provider}'")

        canonical_model = canonical_registry.resolve(provider, model)
        if canonical_model:
            return canonical_model.litellm_model_name, canonical_model

        # kLLM is OpenAI-compatible (`/v1`), so LiteLLM uses the openai
        # adapter with an explicit api_base.
        if provider.lower() == "kllm":
            return f"openai/{model.removeprefix('openai/')}", None

        if provider == "anthropic" and not model.startswith("anthropic/"):
            model = f"anthropic/{model}"
        elif provider == "gemini" and not model.startswith("gemini/"):
            model = f"gemini/{model}"
        elif provider == "deepseek" and not model.startswith("deepseek/"):
            model = f"deepseek/{model}"
        elif provider == "groq" and not model.startswith("groq/"):
            model = f"groq/{model}"
        elif provider == "grok" and not model.startswith("xai/"):
            model = f"xai/{model}"
        elif provider == "nvidia" and not model.startswith("nvidia_nim/"):
            model = f"nvidia_nim/{model}"
        elif provider == "openrouter" and not model.startswith("openrouter/"):
            model = f"openrouter/{model}"
        elif provider == "mistral" and not model.startswith("mistral/"):
            model = f"mistral/{model}"
        elif provider == "ollama_cloud":
            model = model.removeprefix("ollama/")
            if not model.startswith("openai/"):
                model = f"openai/{model}"
        elif provider == "cohere":
            model = model.removeprefix("cohere/")
            if not model.startswith("cohere_chat/"):
                model = f"cohere_chat/{model}"

        return model, None


llm_service = LLMService()
