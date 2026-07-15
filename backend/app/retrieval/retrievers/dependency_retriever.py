import os
import logging
from typing import Optional

from app.retrieval.models import RetrievedContext, RetrievalResult, RetrievalConfig
from app.retrieval.retrievers.base_retriever import BaseRetriever
from app.retrieval.graph_traversal import graph_traversal
from app.indexing.models import RepositoryIndex

logger = logging.getLogger(__name__)


class DependencyRetriever(BaseRetriever):
    @property
    def name(self) -> str:
        return "dependency_retriever"

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

        for changed_file in changed_files:
            file_id = f"file:{changed_file}"

            dependencies = graph_traversal.reachable_nodes(
                index.import_graph,
                file_id,
                edge_type_filter="imports",
            )

            for dep_id in dependencies:
                if dep_id in visited or not dep_id.startswith("file:"):
                    continue
                visited.add(dep_id)

                dep_file = dep_id.replace("file:", "", 1)
                if dep_file in changed_files:
                    continue

                content = self._read_file(repo_path, dep_file, max_lines=200)
                if content:
                    contexts.append(RetrievedContext(
                        file_path=dep_file,
                        content=content,
                        relevance_score=0.7,
                        source="dependency_graph",
                        metadata={"graph_type": "dependency"},
                    ))

        return contexts[:config.max_related_files]

    def _read_file(self, repo_path: str, file_path: str, max_lines: int = 200) -> Optional[str]:
        full_path = os.path.join(repo_path, file_path)
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            if len(lines) > max_lines:
                return "".join(lines[:max_lines]) + f"\n... [{len(lines) - max_lines} more lines]"
            return "".join(lines)
        except OSError:
            return None
