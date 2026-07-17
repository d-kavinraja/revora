import time
import logging
import asyncio
import uuid
from typing import List, Optional
from collections import defaultdict

from app.orchestrator.models import ProviderConfig, LLMResponse, UsageStats
from app.ai.llm import llm_service
from app.prompt_engine.models import CompiledPrompt

logger = logging.getLogger(__name__)

PROVIDER_PRIORITY = [
    ProviderConfig(name="gemini", model="gemini-1.5-flash", priority=0, timeout_seconds=60),
    ProviderConfig(name="openai", model="gpt-4o", priority=1, timeout_seconds=60),
    ProviderConfig(name="anthropic", model="anthropic/claude-sonnet-4-20250514", priority=2, timeout_seconds=60),
    ProviderConfig(name="deepseek", model="deepseek/deepseek-chat", priority=3, timeout_seconds=90),
    ProviderConfig(name="groq", model="groq/llama-3.3-70b-versatile", priority=4, timeout_seconds=30),
]

# Cost per 1K tokens (input/output) by provider
COST_TABLE = {
    "gemini": {"input": 0.000075, "output": 0.0003},
    "openai": {"input": 0.0025, "output": 0.01},
    "anthropic": {"input": 0.003, "output": 0.015},
    "deepseek": {"input": 0.00014, "output": 0.00028},
    "groq": {"input": 0.00059, "output": 0.00079},
}


class LLMOrchestrator:
    def __init__(self):
        self.providers = {p.name: p for p in PROVIDER_PRIORITY}
        self.usage_history: List[UsageStats] = []
        self._error_counts = defaultdict(int)

    async def complete(
        self,
        prompt: CompiledPrompt,
        user_id: str,
        preferred_provider: Optional[str] = None,
        callback=None,
    ) -> LLMResponse:
        ordered_providers = self._get_provider_order(preferred_provider)

        for provider_config in ordered_providers:
            if not provider_config.is_available:
                continue

            for attempt in range(provider_config.max_retries):
                try:
                    start = time.time()
                    if callback:
                        await callback("selecting_ai_provider", "completed", {"provider": provider_config.name, "model": provider_config.model})
                        await callback("sending_request_to_llm", "running")

                    response_text, real_input_tokens, real_output_tokens = await llm_service.get_completion(
                        user_id=__import__("uuid").UUID(user_id),
                        provider=provider_config.name,
                        messages=prompt.get_user_messages(),
                        model=provider_config.model,
                    )

                    # Use real token counts from API; fall back to estimates if API didn't return them
                    input_tokens = real_input_tokens if real_input_tokens > 0 else max(prompt.total_tokens, len(str(prompt.get_user_messages())) // 4)
                    output_tokens = real_output_tokens if real_output_tokens > 0 else (len(response_text) // 4 if response_text else 0)

                    latency_ms = (time.time() - start) * 1000
                    if callback:
                        await callback("sending_request_to_llm", "completed", {"latency_ms": latency_ms})
                        await callback("receiving_ai_response", "completed")

                    usage = UsageStats(
                        provider=provider_config.name,
                        model=provider_config.model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        latency_ms=latency_ms,
                        estimated_cost_usd=self._estimate_cost(provider_config.name, input_tokens, output_tokens),
                    )
                    self.usage_history.append(usage)
                    provider_config.success_rate = min(1.0, provider_config.success_rate + 0.05)
                    self._error_counts[provider_config.name] = 0

                    return LLMResponse(
                        content=response_text,
                        provider=provider_config.name,
                        model=provider_config.model,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                        latency_ms=latency_ms,
                        estimated_cost_usd=usage.estimated_cost_usd,
                        is_fallback=provider_config.name != ordered_providers[0].name,
                    )

                except Exception as e:
                    self._error_counts[provider_config.name] += 1
                    provider_config.success_rate = max(0.0, provider_config.success_rate - 0.1)
                    logger.warning(f"Provider {provider_config.name} attempt {attempt+1} failed: {e}")
                    if attempt < provider_config.max_retries - 1:
                        await asyncio.sleep(min(2 ** attempt, 8))

            provider_config.is_available = False
            logger.warning(f"Provider {provider_config.name} marked unavailable after {provider_config.max_retries} failures")

        raise RuntimeError("All LLM providers failed. Please try again later.")

    def _get_provider_order(self, preferred: Optional[str] = None) -> List[ProviderConfig]:
        if preferred and preferred in self.providers:
            preferred_config = self.providers[preferred]
            others = sorted(
                [p for p in self.providers.values() if p.name != preferred],
                key=lambda p: (p.priority, -p.success_rate),
            )
            return [preferred_config] + others
        return sorted(self.providers.values(), key=lambda p: (p.priority, -p.success_rate))

    def _estimate_cost(self, provider: str, input_tokens: int, output_tokens: int) -> float:
        rates = COST_TABLE.get(provider, {"input": 0.001, "output": 0.003})
        return round((input_tokens * rates["input"] + output_tokens * rates["output"]) / 1000, 6)

    def get_total_usage(self) -> dict:
        total_input = sum(u.input_tokens for u in self.usage_history)
        total_output = sum(u.output_tokens for u in self.usage_history)
        total_cost = sum(u.estimated_cost_usd for u in self.usage_history)
        return {"input_tokens": total_input, "output_tokens": total_output, "total_cost_usd": round(total_cost, 6)}


llm_orchestrator = LLMOrchestrator()

