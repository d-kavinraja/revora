import logging
from typing import Optional

from app.retrieval.models import RetrievedContext
from app.retrieval.compression.base_strategy import BaseCompressionStrategy
from app.retrieval.token_budget_engine import token_budget_engine

logger = logging.getLogger(__name__)


class TruncationStrategy(BaseCompressionStrategy):
    @property
    def name(self) -> str:
        return "truncation"

    async def compress(
        self,
        context: RetrievedContext,
        max_tokens: int,
    ) -> Optional[RetrievedContext]:
        content = context.content
        current_tokens = token_budget_engine.estimate_tokens(content)

        if current_tokens <= max_tokens:
            return context

        truncated = token_budget_engine.truncate_to_budget(content, max_tokens)

        return RetrievedContext(
            file_path=context.file_path,
            content=truncated,
            relevance_score=context.relevance_score,
            source=context.source,
            metadata={**context.metadata, "compressed": True, "compression_strategy": "truncation"},
            compressed=True,
            original_tokens=current_tokens,
        )
