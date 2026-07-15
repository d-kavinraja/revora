import logging
from typing import Optional

from app.retrieval.models import RetrievedContext
from app.retrieval.compression.base_strategy import BaseCompressionStrategy
from app.retrieval.token_budget_engine import token_budget_engine

logger = logging.getLogger(__name__)


class SummarizeStrategy(BaseCompressionStrategy):
    def __init__(self, use_llm: bool = False):
        self._use_llm = use_llm

    @property
    def name(self) -> str:
        return "summarize"

    async def compress(
        self,
        context: RetrievedContext,
        max_tokens: int,
    ) -> Optional[RetrievedContext]:
        content = context.content
        current_tokens = token_budget_engine.estimate_tokens(content)

        if current_tokens <= max_tokens:
            return context

        if not self._use_llm:
            return self._summarize_heuristic(context, content, max_tokens)

        return await self._summarize_llm(context, content, max_tokens)

    def _summarize_heuristic(
        self,
        context: RetrievedContext,
        content: str,
        max_tokens: int,
    ) -> RetrievedContext:
        lines = content.split("\n")

        if not lines:
            return context

        first_line = lines[0] if lines else ""
        summary_lines: list[str] = []

        if first_line.startswith("#") or first_line.startswith("//") or first_line.startswith("/*"):
            summary_lines.append(first_line)

        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(("class ", "def ", "async def", "function ", "func ")):
                summary_lines.append(line)
            elif stripped.startswith(("import ", "from ", "require(", "const ", "let ", "var ")):
                if len(summary_lines) < 20:
                    summary_lines.append(line)

        if len(summary_lines) < len(lines) * 0.3 and len(lines) > 50:
            step = max(1, len(lines) // 30)
            for i in range(0, len(lines), step):
                if lines[i].strip():
                    summary_lines.append(lines[i])

        summary = "\n".join(summary_lines[:60])
        summary_tokens = token_budget_engine.estimate_tokens(summary)

        if summary_tokens > max_tokens:
            summary = token_budget_engine.truncate_to_budget(summary, max_tokens)

        return RetrievedContext(
            file_path=context.file_path,
            content=summary or f"[Summarized: {context.file_path}]",
            relevance_score=context.relevance_score,
            source=context.source,
            metadata={**context.metadata, "compressed": True, "compression_strategy": "heuristic_summary"},
            compressed=True,
            original_tokens=current_tokens,
        )

    async def _summarize_llm(
        self,
        context: RetrievedContext,
        content: str,
        max_tokens: int,
    ) -> RetrievedContext:
        try:
            from app.ai.llm import llm_service
            import uuid

            prompt = (
                f"Summarize the following code file ({context.file_path}) "
                f"in under {max_tokens * 4} characters. "
                f"Focus on: purpose, key exports/classes/functions, and relationships.\n\n"
                f"```\n{content}\n```"
            )

            response = await llm_service.get_completion(
                user_id=uuid.uuid4(),
                provider="gemini",
                messages=[{"role": "user", "content": prompt}],
            )

            if response:
                return RetrievedContext(
                    file_path=context.file_path,
                    content=response[:max_tokens * 4],
                    relevance_score=context.relevance_score,
                    source=context.source,
                    metadata={**context.metadata, "compressed": True, "compression_strategy": "llm_summary"},
                    compressed=True,
                    original_tokens=len(content) // 4,
                )
        except Exception as e:
            logger.debug(f"LLM summarization failed: {e}")

        return self._summarize_heuristic(context, content, max_tokens)
