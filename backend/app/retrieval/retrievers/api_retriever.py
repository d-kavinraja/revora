import os
import logging
from typing import Optional

from app.retrieval.models import RetrievedContext, RetrievalResult, RetrievalConfig
from app.retrieval.retrievers.base_retriever import BaseRetriever
from app.indexing.models import RepositoryIndex

logger = logging.getLogger(__name__)


class APIRetriever(BaseRetriever):
    @property
    def name(self) -> str:
        return "api_retriever"

    async def retrieve(
        self,
        config: RetrievalConfig,
        result: RetrievalResult,
    ) -> list[RetrievedContext]:
        index: Optional[RepositoryIndex] = getattr(result, "_index", None)
        repo_path = getattr(result, "_repo_path", ".")
        changed_files = getattr(result, "_changed_file_paths", [])

        if index is None:
            return []

        contexts = []
        changed_dirs = set()
        for cf in changed_files:
            parts = cf.replace("\\", "/").split("/")
            for i in range(len(parts)):
                changed_dirs.add("/".join(parts[:i+1]))

        for node in index.api_graph.nodes:
            if node.type != "endpoint":
                continue

            endpoint_file = node.file_path
            endpoint_dir = os.path.dirname(endpoint_file).replace("\\", "/")

            is_related = any(
                cd in endpoint_dir or endpoint_dir in cd
                for cd in changed_dirs
            )

            if not is_related and endpoint_file not in changed_files:
                continue

            content = self._read_file(repo_path, endpoint_file, max_lines=100)
            if content:
                contexts.append(RetrievedContext(
                    file_path=endpoint_file,
                    content=content,
                    relevance_score=0.75,
                    source="api_endpoint",
                    metadata={
                        "endpoint": node.name,
                        "method": node.metadata.get("method", ""),
                        "path": node.metadata.get("path", ""),
                    },
                ))

        return contexts[:config.max_related_files]

    def _read_file(self, repo_path: str, file_path: str, max_lines: int = 100) -> Optional[str]:
        full_path = os.path.join(repo_path, file_path)
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            if len(lines) > max_lines:
                return "".join(lines[:max_lines]) + f"\n... [{len(lines) - max_lines} more lines]"
            return "".join(lines)
        except OSError:
            return None
