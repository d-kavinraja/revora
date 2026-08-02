import logging

from app.retrieval.models import RetrievalConfig, RetrievalResult, RetrievedContext
from app.retrieval.retrievers.base_retriever import BaseRetriever
from app.utils.security import safe_join

logger = logging.getLogger(__name__)


class ChangedFileRetriever(BaseRetriever):
    @property
    def name(self) -> str:
        return "changed_file_retriever"

    async def retrieve(
        self,
        config: RetrievalConfig,
        result: RetrievalResult,
    ) -> list[RetrievedContext]:
        contexts = []
        changed_files = getattr(result, "_changed_file_paths", [])

        for file_path in changed_files:
            content = self._read_file(getattr(result, "_repo_path", "."), file_path)
            if content:
                tokens = len(content) // 4
                contexts.append(RetrievedContext(
                    file_path=file_path,
                    content=content,
                    relevance_score=1.0,
                    source="changed_file",
                    metadata={"tokens": tokens},
                ))

        return contexts

    def _read_file(
        self, repo_path: str, file_path: str, max_lines: int = 300
    ) -> str | None:
        try:
            full_path = safe_join(repo_path, file_path)
        except ValueError:
            return None
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            if len(lines) > max_lines:
                return "".join(lines[:max_lines]) + f"\n... [{len(lines) - max_lines} more lines truncated]"
            return "".join(lines)
        except OSError:
            return None
