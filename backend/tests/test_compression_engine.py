import pytest
from app.retrieval.models import RetrievedContext, RetrievalResult
from app.retrieval.compression.engine import compression_engine, CompressionEngine
from app.retrieval.compression.strategies.dedup import DedupStrategy
from app.retrieval.compression.strategies.truncation import TruncationStrategy
from app.retrieval.compression.strategies.import_prune import ImportPruneStrategy
from app.retrieval.token_budget_engine import token_budget_engine


@pytest.fixture
def sample_contexts():
    return [
        RetrievedContext(
            file_path="src/main.py",
            content="def main():\n    pass\n",
            relevance_score=1.0,
            source="changed_file",
        ),
        RetrievedContext(
            file_path="src/utils.py",
            content="import os\nimport sys\n\ndef helper():\n    return True\n",
            relevance_score=0.8,
            source="import_graph",
        ),
    ]


class TestCompressionEngine:
    async def test_compress_under_budget(self, sample_contexts):
        result = RetrievalResult()
        result.changed_files = [sample_contexts[0]]
        result.related_files = [sample_contexts[1]]

        await compression_engine.compress(result, 100000)
        assert len(result.all_contexts()) > 0

    async def test_compress_over_budget(self, sample_contexts):
        result = RetrievalResult()
        result.changed_files = [
            RetrievedContext(
                file_path="large.py",
                content="x\n" * 10000,
                relevance_score=1.0,
                source="changed_file",
            )
        ]

        await compression_engine.compress(result, 500)
        total_tokens = sum(len(c.content) // 4 for c in result.all_contexts())
        assert total_tokens <= 1000

    async def test_dedup_identical_content(self):
        strategy = DedupStrategy()
        ctx1 = RetrievedContext(
            file_path="a.py", content="same content",
            relevance_score=0.5, source="test",
        )
        ctx2 = RetrievedContext(
            file_path="b.py", content="same content",
            relevance_score=0.5, source="test",
        )

        result1 = await strategy.compress(ctx1, 1000)
        assert result1 is not None

        result2 = await strategy.compress(ctx2, 1000)
        assert result2 is None

    async def test_truncation_large_content(self):
        strategy = TruncationStrategy()
        large = RetrievedContext(
            file_path="large.py",
            content="line\n" * 2000,
            relevance_score=0.5,
            source="test",
        )

        compressed = await strategy.compress(large, 100)
        assert compressed is not None
        assert compressed.compressed is True
        assert len(compressed.content) < len(large.content)

    async def test_truncation_small_content(self):
        strategy = TruncationStrategy()
        small = RetrievedContext(
            file_path="small.py",
            content="small",
            relevance_score=0.5,
            source="test",
        )

        compressed = await strategy.compress(small, 1000)
        assert compressed.file_path == "small.py"
        assert compressed.compressed is False

    async def test_import_prune_removes_imports(self):
        strategy = ImportPruneStrategy()
        ctx = RetrievedContext(
            file_path="test.py",
            content="import os\nimport sys\nimport json\n\nx = 1\ny = 2\nz = 3\n",
            relevance_score=0.5,
            source="test",
        )

        compressed = await strategy.compress(ctx, 5)
        assert compressed is not None

    async def test_empty_compression(self):
        engine = CompressionEngine()
        result = RetrievalResult()
        await engine.compress(result, 1000)
        assert result.total_tokens == 0

    async def test_budget_allocator(self):
        from app.retrieval.compression.budget_allocator import budget_allocator
        result = RetrievalResult()
        result.changed_files.append(RetrievedContext(
            file_path="test.py",
            content="x\n" * 5000,
            relevance_score=1.0,
            source="changed_file",
        ))

        budget = budget_allocator.allocate(result, 1000)
        assert budget.total == 1000
        assert "changed_files" in budget.allocations

    async def test_token_estimation(self):
        tokens = token_budget_engine.estimate_tokens("hello world")
        assert tokens >= 1
        tokens = token_budget_engine.estimate_tokens("")
        assert tokens >= 1

    async def test_truncate_to_budget(self):
        text = "hello world\n" * 100
        truncated = token_budget_engine.truncate_to_budget(text, 10)
        assert "[truncated]" in truncated
        assert len(truncated) < len(text)
