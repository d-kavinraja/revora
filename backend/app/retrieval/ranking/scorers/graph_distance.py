from typing import Optional

from app.retrieval.models import RetrievedContext
from app.retrieval.ranking.base_scorer import BaseScorer
from app.indexing.models import RepositoryIndex


class GraphDistanceScorer(BaseScorer):
    @property
    def name(self) -> str:
        return "graph_distance"

    @property
    def weight(self) -> float:
        return 0.25

    async def score(
        self,
        context: RetrievedContext,
        index: Optional[RepositoryIndex] = None,
    ) -> float:
        graph_depth = context.metadata.get("graph_depth")
        if graph_depth is not None:
            score = 1.0 - (min(graph_depth, 5) / 5.0)
            return max(0.1, score)

        source = context.source
        depth_map = {
            "changed_file": 0,
            "test_graph": 1,
            "import_graph": 1,
            "db_schema": 1,
            "dependency_graph": 1,
            "reverse_import": 2,
            "call_graph": 1,
            "api_endpoint": 1,
            "module_graph": 1,
            "security": 2,
            "impact": 2,
            "rule": 3,
            "historical": 3,
            "documentation": 4,
        }

        relative_depth = depth_map.get(source, 5)
        return max(0.1, 1.0 - (relative_depth / 5.0))
