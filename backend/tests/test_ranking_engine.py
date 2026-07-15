import pytest
from app.retrieval.models import RetrievedContext, RetrievalConfig
from app.retrieval.ranking.engine import ranking_engine, RankingEngine
from app.retrieval.ranking.scorers.graph_distance import GraphDistanceScorer
from app.retrieval.ranking.scorers.file_importance import FileImportanceScorer
from app.retrieval.ranking.normalizer import ScoreNormalizer


@pytest.fixture
def sample_contexts():
    return [
        RetrievedContext(
            file_path="src/main.py",
            content="def main():\n    pass\n",
            relevance_score=0.5,
            source="changed_file",
            metadata={"graph_depth": 0},
        ),
        RetrievedContext(
            file_path="src/utils.py",
            content="def helper():\n    return True\n",
            relevance_score=0.5,
            source="import_graph",
            metadata={"graph_depth": 1},
        ),
        RetrievedContext(
            file_path="tests/test_main.py",
            content="def test_main():\n    assert True\n",
            relevance_score=0.5,
            source="test_graph",
            metadata={"graph_depth": 1},
        ),
        RetrievedContext(
            file_path="README.md",
            content="# Documentation\n",
            relevance_score=0.5,
            source="documentation",
            metadata={"graph_depth": 4},
        ),
    ]


class TestRankingEngine:
    async def test_rank_orders_by_relevance(self, sample_contexts):
        ranked = await ranking_engine.rank(sample_contexts)
        assert len(ranked) == 4
        assert ranked[0].relevance_score >= ranked[-1].relevance_score

    async def test_rank_empty_list(self):
        ranked = await ranking_engine.rank([])
        assert ranked == []

    async def test_rank_single_context(self):
        ctx = RetrievedContext(
            file_path="test.py", content="x = 1",
            relevance_score=0.5, source="test",
        )
        ranked = await ranking_engine.rank([ctx])
        assert len(ranked) == 1
        assert ranked[0].file_path == "test.py"

    async def test_rank_position_assigned(self, sample_contexts):
        ranked = await ranking_engine.rank(sample_contexts)
        for i, ctx in enumerate(ranked):
            assert ctx.rank_position == i

    async def test_rank_metadata_scores(self, sample_contexts):
        ranked = await ranking_engine.rank(sample_contexts)
        for ctx in ranked:
            assert "ranking_scores" in ctx.metadata
            assert isinstance(ctx.metadata["ranking_scores"], dict)

    async def test_graph_distance_scorer(self):
        scorer = GraphDistanceScorer()

        close = RetrievedContext(
            file_path="a.py", content="x=1",
            relevance_score=0.5, source="changed_file",
            metadata={"graph_depth": 0},
        )
        far = RetrievedContext(
            file_path="z.py", content="x=1",
            relevance_score=0.5, source="documentation",
            metadata={"graph_depth": 5},
        )

        close_score = await scorer.score(close)
        far_score = await scorer.score(far)
        assert close_score > far_score

    async def test_file_importance_scorer(self):
        scorer = FileImportanceScorer()

        main_file = RetrievedContext(
            file_path="src/main.py", content="x=1",
            relevance_score=0.5, source="test",
        )
        obscure = RetrievedContext(
            file_path="vendor/lib/helper.py", content="x=1",
            relevance_score=0.5, source="test",
        )

        main_score = await scorer.score(main_file)
        obscure_score = await scorer.score(obscure)
        assert main_score >= obscure_score

    async def test_normalizer_min_max(self):
        normalizer = ScoreNormalizer(method="min_max")
        assert normalizer.normalize(0.5) == 0.5
        assert normalizer.normalize(0.0) == 0.0
        assert normalizer.normalize(1.0) == 1.0
        assert 0.4 <= normalizer.normalize(0.4) <= 0.6

    async def test_normalizer_sigmoid(self):
        normalizer = ScoreNormalizer(method="sigmoid")
        result = normalizer.normalize(0.0, midpoint=0.0, steepness=1.0)
        assert result == 0.5

    async def test_empty_ranking(self):
        engine = RankingEngine()
        result = await engine.rank([])
        assert result == []

    async def test_single_scorer_ranking(self):
        engine = RankingEngine()
        engine.register_scorer(GraphDistanceScorer())

        contexts = [
            RetrievedContext(
                file_path="a.py", content="x=1",
                relevance_score=0.5, source="changed_file",
                metadata={"graph_depth": 0},
            ),
            RetrievedContext(
                file_path="b.py", content="x=1",
                relevance_score=0.5, source="documentation",
                metadata={"graph_depth": 5},
            ),
        ]

        ranked = await engine.rank(contexts)
        assert ranked[0].file_path == "a.py"
        assert ranked[1].file_path == "b.py"
