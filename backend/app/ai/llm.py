"""LiteLLM wrapper for LLM API calls.

Provides async interface to multiple LLM providers via LiteLLM,
with user API key resolution from database or environment.
"""

import uuid
import asyncio
import logging
import httpx
from typing import Optional, Tuple

from litellm import completion

from app.ai.model_registry import canonical_registry
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
    ) -> Tuple[Optional[str], int, int]:
        """Fetch the user's API key and call LiteLLM asynchronously.

        Args:
            user_id: User UUID for API key lookup.
            provider: LLM provider name (gemini, openai, anthropic, etc.).
            messages: List of message dicts for the LLM.
            model: Optional model override.
            api_key_id: Optional specific API key ID to use.
            timeout: Timeout in seconds for the LLM call.

        Returns:
            Tuple of (response_text, input_tokens, output_tokens).

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

        model_to_use, canonical_model = self._resolve_model(provider, model)

        try:
            # Run synchronous completion in a thread pool with built-in retries
            # litellm 1.91.x: use max_retries instead of num_retries
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    completion,
                    model=model_to_use,
                    messages=messages,
                    api_key=api_key,
                                    ),
                timeout=timeout,
            )

            # Handle dict responses (litellm sometimes returns dicts instead of ModelResponse)
            if isinstance(response, dict):
                logger.warning(f"litellm returned dict for {model_to_use}: {response}")
                error_msg = response.get("error", {}).get("message", "") if isinstance(response.get("error"), dict) else str(response.get("error", ""))
                raise RuntimeError(f"LLM provider returned error response: {error_msg or response}")

            if response and hasattr(response, "choices") and response.choices and response.choices[0].message:
                content = response.choices[0].message.content
                input_tokens = 0
                output_tokens = 0
                if hasattr(response, "usage") and response.usage:
                    input_tokens = getattr(response.usage, "prompt_tokens", 0) or 0
                    output_tokens = getattr(response.usage, "completion_tokens", 0) or 0
                return content, input_tokens, output_tokens
            return None, 0, 0

        except asyncio.TimeoutError:
            raise RuntimeError(
                f"LLM call to {provider}/{model_to_use} timed out after {timeout}s"
            )
        except Exception as e:
            error_str = str(e).lower()

            # Attempt Gemini Native Fallback if litellm fails due to mapping issues
            if provider == "gemini" and ("404" in error_str or "not found" in error_str or "unsupported" in error_str or "invalid" in error_str):
                logger.info(f"LiteLLM failed for {model_to_use}, attempting native Gemini fallback...")
                native_model = canonical_model.canonical_model_name if canonical_model else model_to_use.replace("gemini/", "")
                try:
                    return await self._native_gemini_fallback(native_model, messages, api_key, timeout)
                except Exception as fallback_e:
                    logger.error(f"Native Gemini fallback also failed: {fallback_e}")
                    e = fallback_e
                    error_str = str(e).lower()
                    model_to_use = native_model

            if "429" in error_str or "rate" in error_str or "quota" in error_str:
                if "free_tier_requests" in error_str or "generaterequestsperday" in error_str:
                    raise RuntimeError(
                        f"Google limits the '{model_to_use}' model to only 20 requests per day on the Free Tier, which you have exceeded. "
                        f"To continue using Revora for free, please edit your Repository Settings and select a model with higher free limits, such as 'gemini-2.5-flash' or 'gemma-4-26b-a4b-it'."
                    ) from e
                
                raise RuntimeError(
                    f"API rate limit exceeded for model '{model_to_use}'. Provider error: {e}"
                ) from e
            elif "401" in error_str or "unauthorized" in error_str:
                raise RuntimeError(
                    f"Invalid API key for {provider}. Please update your API key in Settings > API Keys."
                ) from e
            elif "403" in error_str or "forbidden" in error_str:
                raise RuntimeError(
                    f"API access denied for model '{model_to_use}'. Your API key may not have the required permissions."
                ) from e
            elif "404" in error_str or "not found" in error_str:
                raise RuntimeError(
                    f"Model '{model_to_use}' not found or deprecated by the provider. Please check your provider settings."
                ) from e
            elif "timeout" in error_str:
                raise RuntimeError("AI provider timed out. Please try again later.") from e
            elif "connection" in error_str or "connect" in error_str:
                raise RuntimeError("Unable to connect to AI provider. Please check your network connection.") from e
            else:
                raise RuntimeError(f"AI provider error for '{model_to_use}': {e}") from e

    async def _native_gemini_fallback(self, model: str, messages: list, api_key: str, timeout: int) -> Tuple[Optional[str], int, int]:
        """Fallback adapter for Gemini using native REST API via httpx."""
        gemini_contents = []
        system_instruction = None
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            if role == "system":
                system_instruction = {"parts": [{"text": content}]}
            else:
                g_role = "user" if role == "user" else "model"
                gemini_contents.append({"role": g_role, "parts": [{"text": content}]})

        payload = {"contents": gemini_contents}
        if system_instruction:
            payload["system_instruction"] = system_instruction
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        
        for attempt in range(4):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(url, json=payload, timeout=timeout)
                    resp.raise_for_status()
                    data = resp.json()
                    
                    if "candidates" in data and len(data["candidates"]) > 0:
                        parts = data["candidates"][0].get("content", {}).get("parts", [])
                        if parts and "text" in parts[0]:
                            usage = data.get("usageMetadata", {})
                            input_tokens = usage.get("promptTokenCount", 0) or 0
                            output_tokens = usage.get("candidatesTokenCount", 0) or 0
                            return parts[0]["text"], input_tokens, output_tokens
                    return None, 0, 0
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429 and attempt < 3:
                    wait_time = 2 ** (attempt + 1)
                    logger.warning(f"Native Gemini fallback hit 429. Retrying in {wait_time}s... (Attempt {attempt+1}/3)")
                    await asyncio.sleep(wait_time)
                    continue
                raise e
            except Exception as e:
                raise e

    async def _resolve_api_key(
        self,
        user_id: uuid.UUID,
        provider: str,
        api_key_id: Optional[str] = None,
    ) -> Optional[str]:
        """Resolve API key from database or environment.

        If api_key_id is provided, resolve that specific key.
        Otherwise, get ALL keys for the provider and return the first valid one.
        """
        try:
            async with AsyncSessionLocal() as db:
                if api_key_id:
                    logger.info(f"Resolving API key by id={api_key_id} for user={user_id}")
                    from app.core.security import encryption_service
                    db_key = await api_key_service.get_by_id(db, uuid.UUID(api_key_id))
                    if db_key and db_key.user_id == user_id and db_key.is_valid:
                        decrypted = encryption_service.decrypt(db_key.encrypted_key)
                        logger.info(f"Resolved API key by id: {db_key.label} (provider={db_key.provider})")
                        return decrypted
                    logger.warning(f"API key id={api_key_id} not found or not valid for user={user_id}")
                    return None
                else:
                    logger.info(f"Resolving API key by provider={provider} for user={user_id}")
                    # Try all keys for this provider, preferring recently used
                    all_keys = await api_key_service.get_all_decrypted_keys(db, user_id, provider)
                    if all_keys:
                        key_id, key_value = all_keys[0]
                        logger.info(f"Resolved API key: id={key_id} (provider={provider}, {len(all_keys)} total keys)")
                        return key_value
                    logger.warning(f"No API key found for provider={provider}, user={user_id}")
                    return None
        except Exception as e:
            logger.warning(f"Failed to resolve API key from database: {e}")

    async def _get_all_provider_keys(
        self,
        user_id: uuid.UUID,
        provider: str,
    ) -> list:
        """Get all decrypted API keys for a provider (for retry logic).
        
        Falls back to environment variables if no database keys found.
        """
        try:
            async with AsyncSessionLocal() as db:
                db_keys = await api_key_service.get_all_decrypted_keys(db, user_id, provider)
                if db_keys:
                    return db_keys
        except Exception as e:
            logger.warning(f"Failed to get all API keys from database: {e}")

        # Fallback to environment variables
        from app.core.config import settings
        env_key_map = {
            "gemini": getattr(settings, "GEMINI_API_KEY", None),
            "openai": getattr(settings, "OPENAI_API_KEY", None),
            "anthropic": getattr(settings, "ANTHROPIC_API_KEY", None),
        }
        env_key = env_key_map.get(provider)
        if env_key:
            logger.info(f"Using environment variable API key for provider={provider}")
            return [(None, env_key)]
        return []

    def _resolve_model(self, provider: str, model: Optional[str] = None):
        """Resolve model name through Canonical Model Registry."""
        defaults = {
            "openai": "gpt-4o",
            "anthropic": "claude-3-5-sonnet-20240620",
            "gemini": "gemini-2.5-flash",
            "deepseek": "deepseek-chat",
            "groq": "llama-3.3-70b-versatile",
            "grok": "grok-2",
        }
        
        if not model:
            model = defaults.get(provider)
            if not model:
                raise ValueError(f"Unsupported provider: {provider}")

        # Try to resolve through registry
        canonical_model = canonical_registry.resolve(provider, model)
        if canonical_model:
            return canonical_model.litellm_model_name, canonical_model

        # Fallback to manual resolution if registry is empty or model unknown
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

        return model, None


llm_service = LLMService()







