"""LiteLLM wrapper for LLM API calls.

Provides async interface to multiple LLM providers via LiteLLM,
with user API key resolution from database or environment.
"""

import uuid
import asyncio
import logging
from typing import Optional

from litellm import completion

from app.services.api_key_service import api_key_service
from app.db.session import AsyncSessionLocal
from app.core.constants import LLM_DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)


class LLMService:
    """Async LLM service with provider abstraction."""

    async def get_completion(
        self,
        user_id: uuid.UUID,
        provider: str,
        messages: list,
        model: str = None,
        api_key_id: Optional[str] = None,
        timeout: int = LLM_DEFAULT_TIMEOUT,
    ) -> Optional[str]:
        """Fetch the user's API key and call LiteLLM asynchronously.

        Args:
            user_id: User UUID for API key lookup.
            provider: LLM provider name (gemini, openai, anthropic, etc.).
            messages: List of message dicts for the LLM.
            model: Optional model override.
            api_key_id: Optional specific API key ID to use.
            timeout: Timeout in seconds for the LLM call.

        Returns:
            LLM response text or None on failure.

        Raises:
            ValueError: If no valid API key is found.
            RuntimeError: If LLM call fails after retries.
        """
        api_key = await self._resolve_api_key(user_id, provider, api_key_id)

        if not api_key:
            raise ValueError(
                f"No valid API key found for provider {provider} "
                f"(checked database and env variables)"
            )

        model = self._resolve_model(provider, model)

        try:
            # Run synchronous completion in a thread pool
            # to avoid blocking the asyncio event loop
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    completion,
                    model=model,
                    messages=messages,
                    api_key=api_key,
                ),
                timeout=timeout,
            )

            if response and response.choices and response.choices[0].message:
                return response.choices[0].message.content
            return None

        except asyncio.TimeoutError:
            raise RuntimeError(
                f"LLM call to {provider}/{model} timed out after {timeout}s"
            )
        except Exception as e:
            error_str = str(e).lower()

            if "429" in error_str or "rate" in error_str or "quota" in error_str:
                raise RuntimeError(
                    "API rate limit exceeded or quota exhausted. "
                    "Please check your API key credits."
                ) from e
            elif "401" in error_str or "unauthorized" in error_str:
                raise RuntimeError(
                    "Invalid API key. Please update your API key in Settings > API Keys."
                ) from e
            elif "403" in error_str or "forbidden" in error_str:
                raise RuntimeError(
                    "API access denied. Your API key may not have the required permissions."
                ) from e
            elif "404" in error_str or "not found" in error_str:
                raise RuntimeError(
                    f"Model '{model}' not found. Please check your provider settings."
                ) from e
            elif "timeout" in error_str:
                raise RuntimeError(
                    "AI provider timed out. Please try again later."
                ) from e
            elif "connection" in error_str or "connect" in error_str:
                raise RuntimeError(
                    "Unable to connect to AI provider. Please check your network connection."
                ) from e
            else:
                raise RuntimeError(f"AI provider error: {e}") from e

    async def _resolve_api_key(
        self,
        user_id: uuid.UUID,
        provider: str,
        api_key_id: Optional[str] = None,
    ) -> Optional[str]:
        """Resolve API key from database or environment.

        Args:
            user_id: User UUID.
            provider: Provider name.
            api_key_id: Optional specific key ID.

        Returns:
            Decrypted API key string or None.
        """
        try:
            async with AsyncSessionLocal() as db:
                if api_key_id:
                    from app.core.security import encryption_service

                    db_key = await api_key_service.get_by_id(db, uuid.UUID(api_key_id))
                    if db_key and db_key.user_id == user_id and db_key.is_valid:
                        return encryption_service.decrypt(db_key.encrypted_key)
                    return None
                else:
                    return await api_key_service.get_decrypted_key(
                        db, user_id, provider
                    )
        except Exception as e:
            logger.warning(f"Failed to resolve API key from database: {e}")

        # Fallback to environment variables
        from app.core.config import settings

        env_keys = {
            "gemini": settings.GEMINI_API_KEY,
            "openai": settings.OPENAI_API_KEY,
        }
        return env_keys.get(provider)

    def _resolve_model(self, provider: str, model: Optional[str] = None) -> str:
        """Resolve model name with provider prefix if needed.

        Args:
            provider: Provider name.
            model: Optional model name.

        Returns:
            Resolved model string.
        """
        if not model:
            defaults = {
                "openai": "gpt-4o",
                "anthropic": "claude-3-5-sonnet-20240620",
                "gemini": "gemini-3.5-flash",
                "deepseek": "deepseek-chat",
                "groq": "llama-3.3-70b-versatile",
                "grok": "grok-2",
            }
            model = defaults.get(provider)
            if not model:
                raise ValueError(f"Unsupported provider: {provider}")

        # Add provider prefix for LiteLLM if needed
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

        return model


llm_service = LLMService()
