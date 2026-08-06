"""LiteLLM wrapper for LLM API calls.

Provides async interface to LLM providers via LiteLLM,
with user API key resolution from database.

BYOK Principle: This service uses EXACTLY the key and model it is given.
No fallback, no key cycling, no provider switching.
"""

import asyncio
import logging
import uuid

from litellm import completion

from app.ai.model_registry import canonical_registry
from app.core.constants import LLM_DEFAULT_TIMEOUT
from app.db.session import AsyncSessionLocal
from app.services.api_key_service import api_key_service

logger = logging.getLogger(__name__)


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

        api_key = await self._resolve_api_key(user_id, provider, api_key_id)
        if not api_key:
            raise ValueError(
                f"No valid API key found for provider '{provider}'. "
                f"Please add an API key in Settings > API Keys."
            )

        model_to_use, _ = self._resolve_model(provider, model)

        display_model = model
        if model_to_use.startswith("nvidia_nim/"):
            display_model = model_to_use[len("nvidia_nim/"):]

        effective_timeout = max(timeout or 300, 300)

        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    completion,
                    model=model_to_use,
                    messages=messages,
                    api_key=api_key,
                    num_retries=2,
                ),
                timeout=effective_timeout,
            )

            if isinstance(response, dict):
                logger.warning(f"litellm returned dict for {display_model}: {response}")
                error_msg = (
                    response.get("error", {}).get("message", "")
                    if isinstance(response.get("error"), dict)
                    else str(response.get("error", ""))
                )
                raise RuntimeError(
                    f"LLM provider returned error response: {error_msg or response}"
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
                    output_tokens = (
                        getattr(response.usage, "completion_tokens", 0) or 0
                    )
                return content, input_tokens, output_tokens
            return None, 0, 0

        except TimeoutError:
            raise RuntimeError(
                f"LLM call to {provider}/{display_model} timed out after {effective_timeout}s"
            )
        except Exception as e:
            error_str = str(e).lower()
            if "overloaded" in error_str or "503" in error_str or "busy" in error_str or "capacity" in error_str:
                raise RuntimeError(
                    f"NVIDIA NIM server is temporarily overloaded for '{display_model}'. "
                    f"NVIDIA's API is experiencing high traffic. Please try again in a moment."
                ) from e
            elif "429" in error_str or "rate" in error_str or "quota" in error_str:
                raise RuntimeError(
                    f"Rate limit exceeded for model '{display_model}'. "
                    f"Provider error: {e}"
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
                    f"AI provider error for '{display_model}': {e}"
                ) from e

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

                    db_key = await api_key_service.get_by_id(
                        db, key_uuid
                    )
                    if db_key and db_key.user_id == user_id and db_key.is_valid:
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
            logger.warning(
                f"Failed to get API keys from database: {e}"
            )
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

        return model, None


llm_service = LLMService()







