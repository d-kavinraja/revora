import os
import logging
from typing import Optional

from app.retrieval.models import RetrievedContext, RetrievalResult, RetrievalConfig
from app.retrieval.retrievers.base_retriever import BaseRetriever
from app.retrieval.graph_traversal import graph_traversal
from app.indexing.models import RepositoryIndex

logger = logging.getLogger(__name__)


class ImportRetriever(BaseRetriever):
    @property
    def name(self) -> str:
        return "import_retriever"

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
        visited: set[str] = set()
        max_nodes = config.max_related_files

        for changed_file in changed_files:
            file_id = f"file:{changed_file}"

            neighbors = graph_traversal.k_hop_neighbors(
                index.import_graph,
                file_id,
                k=config.max_depth,
            )

            for neighbor_id, depth in neighbors:
                if neighbor_id in visited or not neighbor_id.startswith("file:"):
                    continue
                visited.add(neighbor_id)

                neighbor_file = neighbor_id.replace("file:", "", 1)
                if neighbor_file in changed_files:
                    continue

                content = self._read_file(repo_path, neighbor_file)
                if content:
                    score = max(0.1, 0.9 - (depth * 0.2))
                    contexts.append(RetrievedContext(
                        file_path=neighbor_file,
                        content=content,
                        relevance_score=score,
                        source="import_graph",
                        metadata={"graph_depth": depth, "graph_type": "import"},
                    ))

                if len(contexts) >= max_nodes:
                    return contexts

        return contexts

    def _read_file(self, repo_path: str, file_path: str, max_lines: int = 300) -> Optional[str]:
        full_path = os.path.join(repo_path, file_path)
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            if len(lines) > max_lines:
                return "".join(lines[:max_lines]) + f"\n... [{len(lines) - max_lines} more lines]"
            return "".join(lines)
        except OSError:
            return None
