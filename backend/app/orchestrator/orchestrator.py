import asyncio
import logging
import time
import uuid

from app.core.config import settings
from app.ai.llm import llm_service
from app.orchestrator.models import (
    CONFIG_SOURCE_REPO,
    CONFIG_SOURCE_ROUTING,
    FallbackRoute,
    LLMResponse,
    UsageStats,
)
from app.prompt_engine.models import CompiledPrompt
from app.services.cost_estimator import cost_estimator

logger = logging.getLogger(__name__)


# ── Transient error classification ──────────────────────────────
# These are errors where retrying the SAME provider/key/model may succeed.
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


class LLMOrchestrator:
    """Executes LLM calls with exactly ONE immutable execution context.

    BYOK Principle:
    - MODE 1 (repo_config): Fail-fast, zero retries, no fallback.
    - MODE 2 (user_routing): Single provider, transient-only retries.
    - Never switches provider, model, or API key.
    """

    def __init__(self):
        self.usage_history: list[UsageStats] = []
        # Per-provider concurrency semaphores (created lazily). Bounds the
        # number of in-flight LLM calls per provider so a burst of parallel
        # reviews does not overwhelm a provider's rate limit.
        self._provider_semaphores: dict[str, asyncio.Semaphore] = {}
        self._provider_limit = max(1, getattr(settings, "PROVIDER_CONCURRENCY_LIMIT", 3))

    def _provider_semaphore(self, provider: str) -> asyncio.Semaphore:
        sem = self._provider_semaphores.get(provider)
        if sem is None:
            sem = asyncio.Semaphore(self._provider_limit)
            self._provider_semaphores[provider] = sem
        return sem

    async def complete(
        self,
        prompt: CompiledPrompt,
        user_id: str,
        config_source: str = CONFIG_SOURCE_ROUTING,
        preferred_provider: str | None = None,
        preferred_model: str | None = None,
        api_key_id: str | None = None,
        callback=None,
        fallback_routes: list[FallbackRoute] | None = None,
        cancel_check=None,
    ) -> LLMResponse:
        """Execute an LLM call, trying the primary then eligible fallbacks.

        The primary keeps its existing retry policy (MODE 1: single attempt,
        MODE 2: transient-only retries). Fallback routes get a single attempt
        each so a request that may have succeeded externally is never
        automatically replayed. The saved repository mapping is never changed;
        fallback only affects the provider actually used for this execution.

        Args:
            prompt: The compiled prompt to send.
            user_id: User UUID string.
            config_source: How the config was resolved (repo_config / user_routing / env_default).
            preferred_provider: The primary provider to use.
            preferred_model: The primary model to use (must be specified).
            api_key_id: The specific API key ID to use for the primary.
            callback: Optional SSE callback for streaming events.
            fallback_routes: Optional ranked alternatives (from ModelRouter).
            cancel_check: Optional async callable returning True when cancelled.

        Returns:
            LLMResponse with content and usage stats.

        Raises:
            RuntimeError: With the exact error message from the provider.
            ValueError: If no valid API key is found.
            asyncio.CancelledError: If cancelled before an attempt.
        """
        if not preferred_provider:
            raise RuntimeError("No provider configured for this review.")

        if not preferred_model:
            raise RuntimeError(
                f"No model configured for provider '{preferred_provider}'."
            )

        try:
            user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
        except ValueError:
            raise ValueError(f"Invalid user ID format: {user_id}")

        # Build the attempt chain: primary first, then ranked fallbacks.
        chain: list[tuple[str, str, str | None, bool]] = [
            (preferred_provider, preferred_model, api_key_id, False)
        ]
        for route in fallback_routes or []:
            if route.provider == preferred_provider and route.model == preferred_model:
                continue
            chain.append((route.provider, route.model, route.api_key_id, True))

        is_explicit = config_source == CONFIG_SOURCE_REPO
        last_error: Exception | None = None

        for provider, model, key_id, is_fallback in chain:
            if cancel_check is not None:
                try:
                    if await cancel_check():
                        raise asyncio.CancelledError()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    pass

            # Primary: MODE 1 single attempt, MODE 2 transient retries.
            # Fallback: always a single attempt (retry-safety).
            max_attempts = 1 if (is_explicit or is_fallback) else 2

            for attempt in range(max_attempts):
                if cancel_check is not None and attempt > 0:
                    try:
                        if await cancel_check():
                            raise asyncio.CancelledError()
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        pass
                try:
                    start = time.time()
                    if callback:
                        await callback(
                            "validating_ai_configuration",
                            "completed",
                            metrics={
                                "provider": provider,
                                "model": model,
                                "config_source": config_source,
                                "fallback": is_fallback,
                            },
                        )
                        await callback("sending_request_to_llm", "running")

                    async with self._provider_semaphore(provider):
                        response_text, real_input_tokens, real_output_tokens = (
                            await llm_service.get_completion(
                                user_id=user_uuid,
                                provider=provider,
                                messages=prompt.get_user_messages(),
                                model=model,
                                api_key_id=key_id,
                            )
                        )

                    input_tokens = (
                        real_input_tokens
                        if real_input_tokens > 0
                        else max(
                            prompt.total_tokens,
                            len(str(prompt.get_user_messages())) // 4,
                        )
                    )
                    output_tokens = (
                        real_output_tokens
                        if real_output_tokens > 0
                        else (len(response_text) // 4 if response_text else 0)
                    )

                    latency_ms = (time.time() - start) * 1000
                    if callback:
                        await callback(
                            "sending_request_to_llm",
                            "completed",
                            metrics={"latency_ms": latency_ms},
                        )
                        await callback("receiving_ai_response", "completed")

                    usage = UsageStats(
                        provider=provider,
                        model=model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        latency_ms=latency_ms,
                        estimated_cost_usd=cost_estimator.estimate(
                            provider, input_tokens, output_tokens
                        ),
                    )
                    self.usage_history.append(usage)

                    logger.info(
                        f"Provider {provider} succeeded"
                        f"{' (fallback)' if is_fallback else ''}: "
                        f"{input_tokens} in / {output_tokens} out / {latency_ms:.0f}ms"
                    )

                    return LLMResponse(
                        content=response_text,
                        provider=provider,
                        model=model,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                        latency_ms=latency_ms,
                        estimated_cost_usd=usage.estimated_cost_usd,
                        is_fallback=is_fallback,
                    )

                except ValueError as e:
                    # No API key — fail immediately
                    raise RuntimeError(f"AI configuration error: {e}") from e

                except Exception as e:
                    last_error = e
                    error_str = str(e).lower()
                    logger.warning(
                        f"Provider {provider} attempt {attempt + 1}/{max_attempts} "
                        f"{' (fallback)' if is_fallback else ''} failed: {e}"
                    )

                    if (
                        attempt < max_attempts - 1
                        and not is_explicit
                        and not is_fallback
                        and _is_transient_error(error_str)
                    ):
                        backoff = min(2**attempt, 4)
                        logger.info(
                            f"Transient error, retrying {provider} "
                            f"in {backoff}s (attempt {attempt + 1}/{max_attempts})..."
                        )
                        await asyncio.sleep(backoff)
                        continue

                    # Exhausted this route — try the next fallback.
                    break

        raise RuntimeError(
            str(last_error)
            if last_error
            else f"Provider {preferred_provider} failed."
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
