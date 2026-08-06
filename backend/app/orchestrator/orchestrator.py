import asyncio
import logging
import time
import uuid

from app.ai.llm import llm_service
from app.orchestrator.models import (
    CONFIG_SOURCE_REPO,
    CONFIG_SOURCE_ROUTING,
    LLMResponse,
    UsageStats,
)
from app.prompt_engine.models import CompiledPrompt
from app.services.cost_estimator import cost_estimator

logger = logging.getLogger(__name__)


# ── Transient error classification ──────────────────────────────
# These are errors where retrying the SAME provider/key/model may succeed.
_TRANSIENT_ERRORS = {"timeout", "connection", "service_unavailable", "503", "500", "502", "504"}


def _is_transient_error(error_str: str) -> bool:
    return any(code in error_str.lower() for code in _TRANSIENT_ERRORS)


class LLMOrchestrator:
    """Executes LLM calls with exactly ONE immutable execution context.

    BYOK Principle:
    - MODE 1 (repo_config): Fail-fast, zero retries, no fallback.
    - MODE 2 (user_routing): Single provider, transient-only retries.
    - Never switches provider, model, or API key.
    """

    def __init__(self):
        self.usage_history: list[UsageStats] = []

    async def complete(
        self,
        prompt: CompiledPrompt,
        user_id: str,
        config_source: str = CONFIG_SOURCE_ROUTING,
        preferred_provider: str | None = None,
        preferred_model: str | None = None,
        api_key_id: str | None = None,
        callback=None,
    ) -> LLMResponse:
        """Execute exactly one LLM call using the resolved execution context.

        Args:
            prompt: The compiled prompt to send.
            user_id: User UUID string.
            config_source: How the config was resolved (repo_config / user_routing / env_default).
            preferred_provider: The provider to use.
            preferred_model: The model to use (must be specified).
            api_key_id: The specific API key ID to use.
            callback: Optional SSE callback for streaming events.

        Returns:
            LLMResponse with content and usage stats.

        Raises:
            RuntimeError: With the exact error message from the provider.
            ValueError: If no valid API key is found.
        """
        if not preferred_provider:
            raise RuntimeError("No provider configured for this review.")

        if not preferred_model:
            raise RuntimeError(f"No model configured for provider '{preferred_provider}'.")

        is_explicit = config_source == CONFIG_SOURCE_REPO
        try:
            user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
        except ValueError:
            raise ValueError(f"Invalid user ID format: {user_id}")

        # ── Single attempt (MODE 1) or transient-retry (MODE 2) ──────
        # For MODE 1: exactly 1 attempt, no retry, no key cycling.
        # For MODE 2: up to 2 attempts (1 initial + 1 transient retry).
        max_attempts = 1 if is_explicit else 2

        last_error: Exception | None = None

        for attempt in range(max_attempts):
            try:
                start = time.time()
                if callback:
                    await callback("validating_ai_configuration", "completed", metrics={
                        "provider": preferred_provider,
                        "model": preferred_model,
                        "config_source": config_source,
                    })
                    await callback("sending_request_to_llm", "running")

                response_text, real_input_tokens, real_output_tokens = (
                    await llm_service.get_completion(
                        user_id=user_uuid,
                        provider=preferred_provider,
                        messages=prompt.get_user_messages(),
                        model=preferred_model,
                        api_key_id=api_key_id,
                    )
                )

                input_tokens = (
                    real_input_tokens
                    if real_input_tokens > 0
                    else max(prompt.total_tokens, len(str(prompt.get_user_messages())) // 4)
                )
                output_tokens = (
                    real_output_tokens
                    if real_output_tokens > 0
                    else (len(response_text) // 4 if response_text else 0)
                )

                latency_ms = (time.time() - start) * 1000
                if callback:
                    await callback("sending_request_to_llm", "completed", metrics={"latency_ms": latency_ms})
                    await callback("receiving_ai_response", "completed")

                usage = UsageStats(
                    provider=preferred_provider,
                    model=preferred_model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                    estimated_cost_usd=cost_estimator.estimate(
                        preferred_provider, input_tokens, output_tokens
                    ),
                )
                self.usage_history.append(usage)

                logger.info(
                    f"Provider {preferred_provider} succeeded: "
                    f"{input_tokens} in / {output_tokens} out / {latency_ms:.0f}ms"
                )

                return LLMResponse(
                    content=response_text,
                    provider=preferred_provider,
                    model=preferred_model,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    latency_ms=latency_ms,
                    estimated_cost_usd=usage.estimated_cost_usd,
                    is_fallback=False,
                )

            except ValueError as e:
                # No API key — fail immediately
                raise RuntimeError(
                    f"AI configuration error: {e}"
                ) from e

            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                logger.warning(
                    f"Provider {preferred_provider} attempt {attempt + 1}/{max_attempts} "
                    f"failed: {e}"
                )

                # Only retry on transient errors (MODE 2 only)
                if attempt < max_attempts - 1 and not is_explicit and _is_transient_error(error_str):
                    backoff = min(2 ** attempt, 4)
                    logger.info(
                        f"Transient error, retrying {preferred_provider} "
                        f"in {backoff}s (attempt {attempt + 1}/{max_attempts})..."
                    )
                    await asyncio.sleep(backoff)
                    continue

                # All other cases: fail immediately
                raise RuntimeError(str(e)) from e

        # Should never reach here, but just in case:
        raise RuntimeError(
            str(last_error) if last_error else f"Provider {preferred_provider} failed."
        )

    def get_total_usage(self) -> dict:
        total_input = sum(u.input_tokens for u in self.usage_history)
        total_output = sum(u.output_tokens for u in self.usage_history)
        total_cost = sum(u.estimated_cost_usd for u in self.usage_history)
        return {
            "input_tokens": total_input,
            "output_tokens": total_output,
            "total_cost_usd": round(total_cost, 6),
        }


llm_orchestrator = LLMOrchestrator()









