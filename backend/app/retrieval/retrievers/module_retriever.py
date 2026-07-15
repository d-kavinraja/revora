import os
import logging
from typing import Optional

from app.retrieval.models import RetrievedContext, RetrievalResult, RetrievalConfig
from app.retrieval.retrievers.base_retriever import BaseRetriever
from app.indexing.models import RepositoryIndex

logger = logging.getLogger(__name__)


class ModuleRetriever(BaseRetriever):
    @property
    def name(self) -> str:
        return "module_retriever"

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

        affected_modules = set()
        file_to_module: dict[str, str] = {}

        for node in index.module_graph.nodes:
            if node.type == "module" and node.file_path:
                file_to_module[node.id] = node.file_path

        for changed_file in changed_files:
            file_id = f"file:{changed_file}"
            for edge in index.module_graph.edges:
                if edge.type == "contains" and edge.target == file_id:
                    affected_modules.add(edge.source)
                    break

        contexts = []
        for module_id in affected_modules:
            module_files = [
                edge.target for edge in index.module_graph.edges
                if edge.source == module_id and edge.type == "contains"
            ]

            sibling_files = [
                mf.replace("file:", "", 1) for mf in module_files
                if mf.replace("file:", "", 1) not in changed_files
            ]

            for sibling in sibling_files[:5]:
                content = self._read_file(repo_path, sibling)
                if content:
                    contexts.append(RetrievedContext(
                        file_path=sibling,
                        content=content,
                        relevance_score=0.6,
                        source="module_graph",
                        metadata={"module_id": module_id, "graph_type": "module"},
                    ))

        return contexts

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
