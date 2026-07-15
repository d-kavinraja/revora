import logging
from typing import Optional

from app.retrieval.models import RetrievedContext
from app.retrieval.ranking.base_scorer import BaseScorer
from app.retrieval.ranking.normalizer import ScoreNormalizer
from app.retrieval.ranking.scorers.graph_distance import GraphDistanceScorer
from app.retrieval.ranking.scorers.file_importance import FileImportanceScorer
from app.retrieval.ranking.scorers.dependency_weight import DependencyWeightScorer
from app.retrieval.ranking.scorers.change_frequency import ChangeFrequencyScorer
from app.retrieval.ranking.scorers.security_impact import SecurityImpactScorer
from app.retrieval.ranking.scorers.test_coverage import TestCoverageScorer
from app.indexing.models import RepositoryIndex

logger = logging.getLogger(__name__)


class RankingEngine:
    def __init__(self):
        self._scorers: list[BaseScorer] = []
        self._normalizer = ScoreNormalizer(method="min_max")

    def register_scorer(self, scorer: BaseScorer) -> None:
        self._scorers.append(scorer)
        logger.info(f"Registered scorer: {scorer.name} (weight={scorer.weight})")

    def set_normalizer(self, method: str) -> None:
        self._normalizer = ScoreNormalizer(method)

    async def rank(
        self,
        contexts: list[RetrievedContext],
        index: Optional[RepositoryIndex] = None,
    ) -> list[RetrievedContext]:
        if not contexts:
            return []

        if not self._scorers:
            logger.warning("No scorers registered; returning contexts unranked")
            return sorted(contexts, key=lambda c: c.relevance_score, reverse=True)

        scored = []
        for ctx in contexts:
            combined = 0.0
            total_weight = 0.0
            scores: dict[str, float] = {}

            for scorer in self._scorers:
                s = await scorer.safe_score(ctx, index)
                normalized = self._normalizer.normalize(s)
                scores[scorer.name] = normalized
                combined += normalized * scorer.weight
                total_weight += scorer.weight

            if total_weight > 0:
                ctx.relevance_score = combined / total_weight
            else:
                ctx.relevance_score = 0.5

            ctx.metadata["ranking_scores"] = scores
            scored.append(ctx)

        ranked = sorted(scored, key=lambda c: c.relevance_score, reverse=True)

        for i, ctx in enumerate(ranked):
            ctx.rank_position = i

        logger.debug(
            f"RankingEngine: ranked {len(ranked)} contexts "
            f"(top score={ranked[0].relevance_score:.2f}, "
            f"bottom score={ranked[-1].relevance_score:.2f})"
        )

        return ranked


ranking_engine = RankingEngine()
ranking_engine.register_scorer(GraphDistanceScorer())
ranking_engine.register_scorer(FileImportanceScorer())
ranking_engine.register_scorer(DependencyWeightScorer())
ranking_engine.register_scorer(ChangeFrequencyScorer())
ranking_engine.register_scorer(SecurityImpactScorer())
ranking_engine.register_scorer(TestCoverageScorer())
