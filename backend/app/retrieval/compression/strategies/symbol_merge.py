import re
import hashlib
import logging
from typing import Optional

from app.retrieval.models import RetrievedContext
from app.retrieval.compression.base_strategy import BaseCompressionStrategy

logger = logging.getLogger(__name__)


class SymbolMergeStrategy(BaseCompressionStrategy):
    def __init__(self):
        self._seen_symbols: dict[str, str] = {}

    @property
    def name(self) -> str:
        return "symbol_merge"

    async def compress(
        self,
        context: RetrievedContext,
        max_tokens: int,
    ) -> Optional[RetrievedContext]:
        content = context.content
        symbols = self._extract_symbols(content)

        if not symbols:
            return context

        has_known_symbols = False
        dedup_lines: set[int] = set()
        lines = content.split("\n")

        for sym_name, sym_line in symbols.items():
            if sym_name in self._seen_symbols and self._seen_symbols[sym_name] != context.file_path:
                for line_num in sym_line:
                    dedup_lines.add(line_num)
                has_known_symbols = True
            else:
                self._seen_symbols[sym_name] = context.file_path

        if not has_known_symbols:
            return context

        new_lines = [
            line for i, line in enumerate(lines)
            if i not in dedup_lines
        ]

        if len(new_lines) < len(lines):
            return RetrievedContext(
                file_path=context.file_path,
                content="\n".join(new_lines),
                relevance_score=context.relevance_score,
                source=context.source,
                metadata={**context.metadata, "compressed": True, "compression_strategy": "symbol_merge"},
                compressed=True,
                original_tokens=len(lines) // 4,
            )

        return context

    def _extract_symbols(self, content: str) -> dict[str, list[int]]:
        symbols: dict[str, list[int]] = {}
        lines = content.split("\n")

        patterns = [
            (r"^(?:def|class|async def)\s+(\w+)", "python"),
            (r"^(?:export\s+)?(?:function|class|const|let|var)\s+(\w+)", "javascript"),
            (r"^func\s+(\w+)", "go"),
            (r"^(?:public|private|protected)?\s*(?:function|class)\s+(\w+)", "java"),
        ]

        for i, line in enumerate(lines):
            for pattern, _ in patterns:
                m = re.match(pattern, line.strip())
                if m:
                    symbols[m.group(1)] = symbols.get(m.group(1), []) + [i]
                    break

        return symbols

    def reset(self) -> None:
        self._seen_symbols.clear()
