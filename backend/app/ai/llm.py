"""LiteLLM wrapper for LLM API calls.

Provides async interface to multiple LLM providers via LiteLLM,
with user API key resolution from database or environment.
"""

import uuid
import asyncio
import logging
import httpx
from typing import Optional

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

        model_to_use, canonical_model = self._resolve_model(provider, model)

        try:
            # Run synchronous completion in a thread pool with built-in retries
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    completion,
                    model=model_to_use,
                    messages=messages,
                    api_key=api_key,
                    num_retries=3,  # LiteLLM will auto-retry on 429s with exponential backoff
                ),
                timeout=timeout,
            )

            if response and response.choices and response.choices[0].message:
                return response.choices[0].message.content
            return None

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
                    # Allow the fallback exception to be processed by the blocks below
                    e = fallback_e
                    error_str = str(e).lower()
                    model_to_use = native_model # Update model name for accurate error messaging

            if "429" in error_str or "rate" in error_str or "quota" in error_str:
                # Provide a highly actionable message for Google's specific 20-request/day free tier limit on 2.0/2.5 models
                if "free_tier_requests" in error_str or "generaterequestsperday" in error_str:
                    raise RuntimeError(
                        f"Google limits the '{model_to_use}' model to only 20 requests per day on the Free Tier, which you have exceeded. "
                        f"To continue using Revora for free, please edit your Repository Settings and select a model with higher free limits, such as 'gemini-1.5-flash' or 'gemma'."
                    ) from e
                
                raise RuntimeError(
                    f"API rate limit exceeded or quota exhausted for model '{model_to_use}'. Provider error: {e}"
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

    async def _native_gemini_fallback(self, model: str, messages: list, api_key: str, timeout: int) -> Optional[str]:
        """Fallback adapter for Gemini using native REST API via httpx."""
        # Convert litellm messages to Gemini format
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
        
        # Exponential backoff loop for rate limits in native adapter
        for attempt in range(4):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(url, json=payload, timeout=timeout)
                    resp.raise_for_status()
                    data = resp.json()
                    
                    if "candidates" in data and len(data["candidates"]) > 0:
                        parts = data["candidates"][0].get("content", {}).get("parts", [])
                        if parts and "text" in parts[0]:
                            return parts[0]["text"]
                    return None
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429 and attempt < 3:
                    # Exponential backoff: wait 2s, 4s, 8s
                    wait_time = 2 ** (attempt + 1)
                    logger.warning(f"Native Gemini fallback hit 429. Retrying in {wait_time}s... (Attempt {attempt+1}/3)")
                    await asyncio.sleep(wait_time)
                    continue
                raise e
            except Exception as e:
                # Other exceptions raise immediately
                raise e

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

    def _resolve_model(self, provider: str, model: Optional[str] = None):
        """Resolve model name through Canonical Model Registry.

        Returns:
            Tuple of (resolved_litellm_model_str, CanonicalModel or None)
        """
        defaults = {
            "openai": "gpt-4o",
            "anthropic": "claude-3-5-sonnet-20240620",
            "gemini": "gemini-1.5-flash",
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
