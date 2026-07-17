import uuid
import time
import asyncio
import logging
from typing import Optional, List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.health_monitor import health_monitor
from app.services.token_manager import token_manager
from app.services.cost_estimator import cost_estimator
from app.services.api_key_service import api_key_service
from app.ai.llm import LLMService
from app.orchestrator.models import LLMResponse

logger = logging.getLogger(__name__)


class RetryFailoverService:
    def __init__(self):
        self.llm_service = LLMService()

    async def execute_with_fallback(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        feature: str,
        messages: list,
        routes: List[Tuple[str, str, Optional[str]]],  # (provider, model, api_key_id)
        max_retries: int = 2,
    ) -> LLMResponse:
        last_error = None
        overall_start = time.time()

        for attempt_idx, (provider, model, api_key_id) in enumerate(routes):
            if not await health_monitor.should_allow_request(db, provider):
                logger.warning(f"Circuit breaker open for {provider}, skipping")
                continue

            for retry in range(max_retries):
                try:
                    start = time.time()
                    response_text, real_input_tokens, real_output_tokens = await self.llm_service.get_completion(
                        user_id=user_id,
                        provider=provider,
                        messages=messages,
                        model=model,
                        api_key_id=api_key_id,
                    )
                    latency_ms = (time.time() - start) * 1000

                    if response_text:
                        await health_monitor.record_success(db, provider, latency_ms)

                        # Use real token counts from API if available; fall back to estimates
                        input_tokens = real_input_tokens if real_input_tokens > 0 else sum(len(m.get("content", "")) // 4 for m in messages) if messages else 0
                        output_tokens = real_output_tokens if real_output_tokens > 0 else len(response_text) // 4

                        # Mark key as used
                        if api_key_id:
                            try:
                                await api_key_service.mark_last_used(db, uuid.UUID(api_key_id))
                            except Exception:
                                pass

                        return LLMResponse(
                            content=response_text,
                            provider=provider,
                            model=model,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            latency_ms=latency_ms,
                            estimated_cost_usd=cost_estimator.estimate(provider, input_tokens, output_tokens),
                            is_fallback=attempt_idx > 0,
                        )

                except Exception as e:
                    last_error = str(e)
                    logger.warning(f"Provider {provider} attempt {retry+1} failed: {e}")
                    await health_monitor.record_failure(db, provider, type(e).__name__, str(e))

                    if retry < max_retries - 1:
                        await asyncio.sleep(min(2 ** retry, 8))

            if attempt_idx < len(routes) - 1:
                next_provider = routes[attempt_idx + 1][0]
                await health_monitor.log_failover(
                    db, user_id, feature,
                    failed_provider=provider,
                    failed_model=model,
                    failure_reason=last_error or "Unknown error",
                    fallback_provider=next_provider,
                    fallback_model=routes[attempt_idx + 1][1],
                    attempt_number=attempt_idx + 1,
                    total_latency_ms=(time.time() - overall_start) * 1000,
                )

        raise RuntimeError(f"All providers failed. Last error: {last_error}")


retry_failover = RetryFailoverService()
