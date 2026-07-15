import re
import logging
from typing import Optional

from app.retrieval.models import RetrievedContext
from app.retrieval.compression.base_strategy import BaseCompressionStrategy
from app.retrieval.token_budget_engine import token_budget_engine

logger = logging.getLogger(__name__)


class ImportPruneStrategy(BaseCompressionStrategy):
    @property
    def name(self) -> str:
        return "import_prune"

    async def compress(
        self,
        context: RetrievedContext,
        max_tokens: int,
    ) -> Optional[RetrievedContext]:
        content = context.content
        current_tokens = token_budget_engine.estimate_tokens(content)

        if current_tokens <= max_tokens:
            return context

        lines = content.split("\n")
        import_lines: list[int] = []
        non_import_lines: list[int] = []

        for i, line in enumerate(lines):
            stripped = line.strip()
            if re.match(r"^(import |from |require\()", stripped):
                import_lines.append(i)
            elif re.match(r"^#|^//|^/\*|^\*", stripped):
                import_lines.append(i)
            elif stripped == "" and import_lines and i == import_lines[-1] + 1:
                import_lines.append(i)
            else:
                non_import_lines.append(i)

        if not import_lines:
            return context

        pruned_lines = [lines[i] for i in non_import_lines]
        pruned = "\n".join(pruned_lines)

        pruned_tokens = token_budget_engine.estimate_tokens(pruned)
        if pruned_tokens <= max_tokens:
            return RetrievedContext(
                file_path=context.file_path,
                content=pruned,
                relevance_score=context.relevance_score,
                source=context.source,
                metadata={**context.metadata, "compressed": True, "compression_strategy": "import_prune"},
                compressed=True,
                original_tokens=current_tokens,
            )

        return context
