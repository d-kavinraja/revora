"""Prompt validation before LLM submission.

Validates prompt size, token count, sections, and provider limits.
"""

import logging
from dataclasses import dataclass, field
from typing import List

from app.prompt_engine.models import CompiledPrompt, PromptBuildRequest

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of prompt validation."""
    valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


PROVIDER_LIMITS = {
    "gemini": {"context_window": 1000000, "max_output": 8192},
    "openai": {"context_window": 128000, "max_output": 4096},
    "anthropic": {"context_window": 200000, "max_output": 8192},
    "deepseek": {"context_window": 128000, "max_output": 4096},
    "groq": {"context_window": 128000, "max_output": 4096},
}


class PromptValidator:
    """Validates prompts before they reach the LLM."""

    async def validate(self, prompt: CompiledPrompt, request: PromptBuildRequest) -> ValidationResult:
        """Validate prompt size, token count, sections, metadata, provider limits."""
        result = ValidationResult()

        if not prompt.system_prompt:
            result.errors.append("Missing system prompt")
            result.valid = False

        if not prompt.user_prompt:
            result.warnings.append("Empty user prompt")

        if prompt.total_tokens <= 0:
            result.errors.append("Prompt has zero tokens")
            result.valid = False

        provider = request.provider
        if provider in PROVIDER_LIMITS:
            limits = PROVIDER_LIMITS[provider]
            if prompt.total_tokens > limits["context_window"]:
                result.errors.append(
                    f"Prompt ({prompt.total_tokens} tokens) exceeds {provider} context window ({limits['context_window']})"
                )
                result.valid = False

        if not prompt.prompt_id:
            result.warnings.append("Missing prompt ID")

        if not prompt.cache_key:
            result.warnings.append("Missing cache key")

        if prompt.build_time_ms > 5000:
            result.warnings.append(f"Slow prompt build: {prompt.build_time_ms:.0f}ms")

        return result
