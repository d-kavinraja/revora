"""Prompt optimization for token budget compliance.

Deduplicates, trims, and fits sections within the configured token budget.
"""

import logging
from typing import Dict, Optional

from app.prompt_engine.models import PromptSection, PromptBuildRequest, TokenMetadata
from app.prompt_engine.token_budget import PromptTokenBudget, estimate_tokens

logger = logging.getLogger(__name__)


class PromptOptimizer:
    """Optimizes prompt sections to fit within token budget."""

    async def optimize(
        self,
        sections: Dict[str, PromptSection],
        budget_manager: PromptTokenBudget,
    ) -> Dict[str, PromptSection]:
        """Optimize sections to fit within token budget.

        Strategy:
        1. First pass: include all sections within their allocations
        2. Second pass: trim oversized sections by priority
        3. Third pass: remove lowest-priority sections if still over budget
        """
        if not sections:
            return sections

        optimized = {}

        sorted_sections = sorted(sections.values(), key=lambda s: s.priority, reverse=True)

        for section in sorted_sections:
            if section.name == "system_instructions":
                optimized[section.name] = section
                budget_manager.allocate(section.name, section.token_count)
                continue

            tokens = section.token_count
            if budget_manager.can_fit(section.name, tokens):
                optimized[section.name] = section
                budget_manager.allocate(section.name, tokens)
            else:
                allocation = budget_manager.get_allocation(section.name)
                if allocation > 0 and section.content:
                    truncated = self._truncate_to_tokens(section.content, allocation)
                    trimmed_section = PromptSection(
                        name=section.name,
                        content=truncated,
                        token_count=estimate_tokens(truncated),
                        version=section.version,
                        priority=section.priority,
                        compressed=True,
                        source_files=section.source_files,
                    )
                    optimized[section.name] = trimmed_section
                    budget_manager.allocate(section.name, trimmed_section.token_count)

        return optimized

    def _truncate_to_tokens(self, content: str, max_tokens: int) -> str:
        """Truncate content to fit within max_tokens."""
        max_chars = max_tokens * 4
        if len(content) <= max_chars:
            return content

        truncated = content[:max_chars - 50]
        last_newline = truncated.rfind("\n")
        if last_newline > max_chars * 0.8:
            truncated = truncated[:last_newline]

        return truncated + "\n\n... (truncated to fit token budget)"
