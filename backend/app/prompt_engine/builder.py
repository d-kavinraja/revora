import hashlib
import logging
from typing import Dict, Optional

from app.prompt_engine.models import CompiledPrompt, PromptSection
from app.prompt_engine.templates import (
    SYSTEM_PROMPT,
    REPO_CONTEXT_TEMPLATE,
    CHANGED_FILES_TEMPLATE,
    RELATED_CONTEXT_TEMPLATE,
    ANALYSIS_TEMPLATE,
    OUTPUT_FORMAT_TEMPLATE,
)

logger = logging.getLogger(__name__)


class PromptBuilder:
    """Builds modular prompts for code review."""

    async def compile(
        self,
        repo_summary: str = "",
        architecture_summary: str = "",
        conventions: str = "",
        rules: list[str] = None,
        diff_content: str = "",
        related_files: list[dict] = None,
        static_analysis: str = "",
    ) -> CompiledPrompt:
        prompt = CompiledPrompt()

        # System prompt
        prompt.system_prompt = SYSTEM_PROMPT

        # Build user prompt sections
        sections = []

        # Repository context
        rules_text = "\n".join(f"- {r}" for r in (rules or []))
        repo_context = REPO_CONTEXT_TEMPLATE.format(
            repo_summary=repo_summary or "No repository summary available.",
            architecture_summary=architecture_summary or "No architecture information available.",
            conventions=conventions or "No conventions detected.",
            rules=rules_text or "No specific rules.",
        )
        sections.append(repo_context)

        # Changed files
        if diff_content:
            sections.append(CHANGED_FILES_TEMPLATE.format(diff_content=diff_content))

        # Related context
        if related_files:
            related_text = ""
            for rf in related_files:
                path = rf.get("file_path", "")
                content = rf.get("content", "")
                related_text += f"\n### {path}\n```\n{content[:1000]}\n```\n"
            sections.append(RELATED_CONTEXT_TEMPLATE.format(related_files=related_text))

        # Static analysis
        if static_analysis:
            sections.append(f"## Static Analysis Results\n\n{static_analysis}")

        # Analysis instructions
        sections.append(ANALYSIS_TEMPLATE)

        # Output format
        sections.append(OUTPUT_FORMAT_TEMPLATE)

        prompt.user_prompt = "\n\n".join(sections)

        # Calculate tokens (rough estimate)
        prompt.total_tokens = (len(prompt.system_prompt) + len(prompt.user_prompt)) // 4

        # Generate cache key
        cache_content = prompt.system_prompt + prompt.user_prompt
        prompt.cache_key = hashlib.sha256(cache_content.encode()).hexdigest()[:16]

        logger.info(f"Compiled prompt: {prompt.total_tokens} tokens, cache_key={prompt.cache_key}")
        return prompt


prompt_builder = PromptBuilder()
