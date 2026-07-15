from typing import Optional

from app.retrieval.models import RetrievedContext
from app.retrieval.ranking.base_scorer import BaseScorer
from app.indexing.models import RepositoryIndex


class FileImportanceScorer(BaseScorer):
    @property
    def name(self) -> str:
        return "file_importance"

    @property
    def weight(self) -> float:
        return 0.20

    async def score(
        self,
        context: RetrievedContext,
        index: Optional[RepositoryIndex] = None,
    ) -> float:
        file_path = context.file_path
        score = 0.5

        entry_point_keywords = [
            "main", "index", "app", "server", "cli", "entry",
            "router", "__init__", "middleware",
        ]
        for kw in entry_point_keywords:
            if kw in file_path.lower():
                score += 0.15
                break

        core_keywords = [
            "core", "base", "config", "settings", "constants",
            "types", "interfaces", "abstract", "contract",
        ]
        for kw in core_keywords:
            if kw in file_path.lower():
                score += 0.1
                break

        if index:
            file_id = f"file:{file_path}"
            for graph_name in ("import_graph", "call_graph"):
                graph = getattr(index, graph_name, None)
                if graph is None:
                    continue
                edges_from = graph.get_edges_from(file_id)
                edges_to = graph.get_edges_to(file_id)
                degree = len(edges_from) + len(edges_to)
                if degree > 20:
                    score += 0.2
                elif degree > 10:
                    score += 0.1
                elif degree > 0:
                    score += 0.05

        return min(1.0, score)
