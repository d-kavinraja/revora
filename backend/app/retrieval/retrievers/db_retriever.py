import os
import logging
from typing import Optional

from app.retrieval.models import RetrievedContext, RetrievalResult, RetrievalConfig
from app.retrieval.retrievers.base_retriever import BaseRetriever
from app.indexing.models import RepositoryIndex

logger = logging.getLogger(__name__)


class DBRetriever(BaseRetriever):
    @property
    def name(self) -> str:
        return "db_retriever"

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

        changed_model_files = {
            cf for cf in changed_files
            if any(name in cf.lower() for name in ("model", "schema", "entity", "table", "migration"))
        }

        if not changed_model_files and not any(
            n.type == "table" for n in index.db_graph.nodes
        ):
            return []

        contexts = []
        changed_file_ids = {f"file:{cf}" for cf in changed_files}

        for edge in index.db_graph.edges:
            if edge.type != "defines":
                continue

            file_id = edge.source
            model_node = index.db_graph.get_node(edge.target)

            if model_node is None or model_node.type != "table":
                continue

            if file_id not in changed_file_ids:
                continue

            content = self._read_file(repo_path, model_node.file_path, max_lines=150)
            if content:
                contexts.append(RetrievedContext(
                    file_path=model_node.file_path,
                    content=content,
                    relevance_score=0.85,
                    source="db_schema",
                    metadata={
                        "model_name": model_node.name,
                        "orm": model_node.metadata.get("orm", ""),
                    },
                ))

        return contexts[:config.max_related_files]

    def _read_file(self, repo_path: str, file_path: str, max_lines: int = 150) -> Optional[str]:
        full_path = os.path.join(repo_path, file_path)
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            if len(lines) > max_lines:
                return "".join(lines[:max_lines]) + f"\n... [{len(lines) - max_lines} more lines]"
            return "".join(lines)
        except OSError:
            return None
