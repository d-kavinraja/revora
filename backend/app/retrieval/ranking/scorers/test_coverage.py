from typing import Optional

from app.retrieval.models import RetrievedContext
from app.retrieval.ranking.base_scorer import BaseScorer
from app.indexing.models import RepositoryIndex


class TestCoverageScorer(BaseScorer):
    @property
    def name(self) -> str:
        return "test_coverage"

    @property
    def weight(self) -> float:
        return 0.10

    async def score(
        self,
        context: RetrievedContext,
        index: Optional[RepositoryIndex] = None,
    ) -> float:
        if index is None:
            return 0.5

        file_path = context.file_path
        file_id = f"file:{file_path}"

        test_graph = index.test_graph
        has_test = any(
            edge.source == file_id and edge.type == "tests"
            for edge in test_graph.edges
        )

        if has_test:
            return 0.8

        is_test_file = any(
            node.file_path == file_path and node.metadata.get("is_test")
            for node in test_graph.nodes
            if node.type == "file"
        )

        if is_test_file:
            return 0.7

        return 0.4
