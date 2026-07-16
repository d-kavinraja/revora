"""Context ranking for prompt building.

Ranks and prioritizes context from RetrievalResult before it enters sections.
Uses priority weights based on context source type.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


PRIORITY_WEIGHTS = {
    "changed_file": 10,
    "import_graph": 9,
    "reverse_import": 9,
    "test_graph": 8,
    "config": 7,
    "documentation": 6,
    "rule": 5,
    "historical": 4,
    "dependency_graph": 3,
    "call_graph": 3,
    "module_graph": 2,
    "api_endpoint": 3,
    "db_schema": 3,
    "security": 5,
    "impact": 4,
}


@dataclass
class RankedContext:
    """Ranked and prioritized context ready for section building."""
    rankable_contexts: list = field(default_factory=list)
    total_tokens: int = 0
    files_count: int = 0
    sources_used: list = field(default_factory=list)


class ContextRanker:
    """Ranks context from RetrievalResult by priority and relevance."""

    def __init__(self):
        self.priority_weights = PRIORITY_WEIGHTS.copy()

    async def rank_contexts(self, retrieval_result, token_budget: int = 10000) -> RankedContext:
        """Flatten all 11 buckets, rank by priority*relevance, return within budget."""
        if not retrieval_result:
            return RankedContext()

        all_contexts = []

        bucket_attrs = [
            "changed_files", "related_files", "test_files", "config_files",
            "api_endpoints", "db_schemas", "security_context", "impact_context",
            "historical_context", "rule_context", "documentation_context",
        ]

        for attr in bucket_attrs:
            contexts = getattr(retrieval_result, attr, [])
            if contexts:
                all_contexts.extend(contexts)

        if not all_contexts:
            return RankedContext()

        for ctx in all_contexts:
            ctx._priority = self.priority_weights.get(ctx.source, 0)
            ctx._combined_score = ctx._priority * ctx.relevance_score

        all_contexts.sort(key=lambda c: c._combined_score, reverse=True)

        budget_tokens = token_budget
        selected = []
        current_tokens = 0

        for ctx in all_contexts:
            ctx_tokens = len(ctx.content) // 4
            if current_tokens + ctx_tokens <= budget_tokens:
                selected.append(ctx)
                current_tokens += ctx_tokens
            else:
                remaining = budget_tokens - current_tokens
                if remaining > 200 and ctx.content:
                    truncated_content = ctx.content[:remaining * 4]
                    ctx_copy = _copy_context(ctx, truncated_content)
                    selected.append(ctx_copy)
                    current_tokens += remaining
                break

        sources_used = list(set(ctx.source for ctx in selected))

        return RankedContext(
            rankable_contexts=selected,
            total_tokens=current_tokens,
            files_count=len(selected),
            sources_used=sources_used,
        )


def _copy_context(ctx, new_content):
    """Create a copy of a RetrievedContext with modified content."""
    from app.retrieval.models import RetrievedContext
    return RetrievedContext(
        file_path=ctx.file_path,
        content=new_content,
        relevance_score=ctx.relevance_score,
        source=ctx.source,
        metadata=ctx.metadata,
        compressed=True,
        original_tokens=len(ctx.content) // 4,
        rank_position=getattr(ctx, 'rank_position', 0),
    )
