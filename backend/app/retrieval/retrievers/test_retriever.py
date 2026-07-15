import os
import logging
from typing import Optional

from app.retrieval.models import RetrievedContext, RetrievalResult, RetrievalConfig
from app.retrieval.retrievers.base_retriever import BaseRetriever
from app.retrieval.graph_traversal import graph_traversal
from app.indexing.models import RepositoryIndex

logger = logging.getLogger(__name__)


class TestRetriever(BaseRetriever):
    @property
    def name(self) -> str:
        return "test_retriever"

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
        seen_test_files: set[str] = set()

        for changed_file in changed_files:
            test_nodes = graph_traversal.reachable_nodes(
                index.test_graph,
                f"file:{changed_file}",
                reverse=True,
            )

            for test_node_id in test_nodes:
                if not test_node_id.startswith("test_file:"):
                    continue

                test_file = test_node_id.replace("test_file:", "", 1)
                if test_file in seen_test_files:
                    continue
                seen_test_files.add(test_file)

                content = self._read_file(repo_path, test_file, max_lines=150)
                if content:
                    contexts.append(RetrievedContext(
                        file_path=test_file,
                        content=content,
                        relevance_score=0.85,
                        source="test_graph",
                        metadata={"test_file": True, "tested_file": changed_file},
                    ))

        return contexts[:config.max_test_files]

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
