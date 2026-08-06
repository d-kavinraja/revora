import asyncio
import logging
import time
import uuid

from app.ai.llm import llm_service
from app.orchestrator.models import LLMResponse
from app.services.api_key_service import api_key_service
from app.services.cost_estimator import cost_estimator

logger = logging.getLogger(__name__)

# Transient errors where retrying the SAME provider/key/model may succeed
_TRANSIENT_ERRORS = {
    "timeout",
    "connection",
    "service_unavailable",
    "503",
    "500",
    "502",
    "504",
}


def _is_transient_error(error_str: str) -> bool:
    return any(code in error_str.lower() for code in _TRANSIENT_ERRORS)


class RetryFailoverService:
    """Single-provider execution with optional transient retry.

    BYOK-compliant: Never switches provider, model, or API key.
    Retries only for transient transport errors on the SAME configuration.
    """

    def __init__(self):
        self.llm_service = llm_service

    async def execute(
        self,
        user_id: uuid.UUID,
        provider: str,
        model: str,
        messages: list,
        api_key_id: str | None = None,
        max_retries: int = 1,
    ) -> LLMResponse:
        """Execute exactly one LLM call with the given provider/model/key.

        Args:
            user_id: User UUID.
            provider: Provider name.
            model: Model name.
            messages: List of message dicts.
            api_key_id: Specific API key ID.
            max_retries: Max retries for transient errors (default 1 = 2 total attempts).

        Returns:
            LLMResponse with content and usage stats.
        """
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                start = time.time()
                response_text, real_input_tokens, real_output_tokens = (
                    await self.llm_service.get_completion(
                        user_id=user_id,
                        provider=provider,
                        messages=messages,
                        model=model,
                        api_key_id=api_key_id,
                    )
                )
                latency_ms = (time.time() - start) * 1000

                input_tokens = (
                    real_input_tokens
                    if real_input_tokens > 0
                    else (
                        sum(len(m.get("content", "")) // 4 for m in messages)
                        if messages
                        else 0
                    )
                )
                output_tokens = (
                    real_output_tokens
                    if real_output_tokens > 0
                    else len(response_text) // 4 if response_text else 0
                )

                if api_key_id:
                    try:
                        await api_key_service.mark_last_used(
                            None, uuid.UUID(api_key_id)
                        )
                    except Exception:
                        pass

                return LLMResponse(
                    content=response_text,
                    provider=provider,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                    estimated_cost_usd=cost_estimator.estimate(
                        provider, input_tokens, output_tokens
                    ),
                    is_fallback=False,
                )

            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                logger.warning(
                    f"Provider {provider} attempt {attempt + 1}/{max_retries + 1} failed: {e}"
                )

                if attempt < max_retries and _is_transient_error(error_str):
                    backoff = min(2**attempt, 4)
                    logger.info(
                        f"Transient error, retrying {provider} in {backoff}s..."
                    )
                    await asyncio.sleep(backoff)
                    continue

                raise  # Non-transient or out of retries

        # Should never reach here
        raise RuntimeError(
            str(last_error) if last_error else f"Provider {provider} failed."
        )


retry_failover = RetryFailoverService()
