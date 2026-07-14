import uuid
from typing import Optional
from litellm import completion

from app.services.api_key_service import api_key_service
from app.db.session import AsyncSessionLocal

class LLMService:
    async def get_completion(
        self,
        user_id: uuid.UUID,
        provider: str,
        messages: list,
        model: str = None,
        api_key_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Fetch the user's API key and call LiteLLM.
        """
        async with AsyncSessionLocal() as db:
            if api_key_id:
                from app.core.security import encryption_service
                db_key = await api_key_service.get_by_id(db, uuid.UUID(api_key_id))
                if db_key and db_key.user_id == user_id and db_key.is_valid:
                    api_key = encryption_service.decrypt(db_key.encrypted_key)
                else:
                    api_key = None
            else:
                api_key = await api_key_service.get_decrypted_key(db, user_id, provider)
            
        if not api_key:
            from app.core.config import settings
            if provider == "gemini":
                api_key = settings.GEMINI_API_KEY
            elif provider == "openai":
                api_key = settings.OPENAI_API_KEY
                
        if not api_key:
            raise ValueError(f"No valid API key found for provider {provider} (checked database and env variables)")

        # Default models based on provider if not specified
        if not model:
            if provider == "openai":
                model = "gpt-4o"
            elif provider == "anthropic":
                model = "claude-3-5-sonnet-20240620"
            elif provider == "gemini":
                model = "gemini-3.1-flash-lite"
            else:
                raise ValueError(f"Unsupported provider: {provider}")

        # Add provider prefix for LiteLLM if needed
        if provider == "anthropic" and not model.startswith("anthropic/"):
            model = f"anthropic/{model}"
        elif provider == "gemini" and not model.startswith("gemini/"):
            model = f"gemini/{model}"

        # LiteLLM abstract call
        try:
            response = completion(
                model=model,
                messages=messages,
                api_key=api_key
            )
            return response.choices[0].message.content
        except Exception as e:
            error_str = str(e).lower()

            if "429" in error_str or "rate" in error_str or "quota" in error_str:
                raise RuntimeError("API rate limit exceeded or quota exhausted. Please check your API key credits.") from e
            elif "401" in error_str or "unauthorized" in error_str:
                raise RuntimeError("Invalid API key. Please update your API key in Settings > API Keys.") from e
            elif "403" in error_str or "forbidden" in error_str:
                raise RuntimeError("API access denied. Your API key may not have the required permissions.") from e
            elif "404" in error_str or "not found" in error_str:
                raise RuntimeError(f"Model '{model}' not found. Please check your provider settings.") from e
            elif "timeout" in error_str:
                raise RuntimeError("AI provider timed out. Please try again later.") from e
            elif "connection" in error_str or "connect" in error_str:
                raise RuntimeError("Unable to connect to AI provider. Please check your network connection.") from e
            else:
                raise RuntimeError(f"AI provider error: {e}") from e

llm_service = LLMService()
