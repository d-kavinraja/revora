from typing import Optional

from app.retrieval.models import RetrievedContext
from app.retrieval.ranking.base_scorer import BaseScorer
from app.indexing.models import RepositoryIndex


class DependencyWeightScorer(BaseScorer):
    @property
    def name(self) -> str:
        return "dependency_weight"

    @property
    def weight(self) -> float:
        return 0.15

    async def score(
        self,
        context: RetrievedContext,
        index: Optional[RepositoryIndex] = None,
    ) -> float:
        if index is None:
            return 0.5

        file_path = context.file_path
        file_id = f"file:{file_path}"

        import_graph = index.import_graph
        incoming = len(import_graph.get_edges_to(file_id))
        outgoing = len(import_graph.get_edges_from(file_id))

        total_edges = incoming + outgoing
        if total_edges == 0:
            return 0.3

        max_edges = max(
            len(import_graph.get_edges_to(n.id)) + len(import_graph.get_edges_from(n.id))
            for n in import_graph.nodes
        ) or 1

        return min(1.0, (incoming * 1.5 + outgoing * 0.5) / max_edges)
