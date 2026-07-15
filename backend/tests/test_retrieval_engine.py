import pytest
from app.retrieval.engine import RetrievalEngine, retrieval_engine
from app.retrieval.models import RetrievalResult, RetrievalConfig, RetrievedContext
from app.retrieval.fallback import retrieval_fallback
from app.indexing.models import RepositoryIndex, CodeGraph, GraphNode, GraphEdge


class TestRetrievalEngine:
    async def test_retrieve_no_index(self):
        engine = RetrievalEngine()
        config = RetrievalConfig(budget=10000, enable_graph_traversal=False)
        engine.configure(config)

        result = await engine.retrieve(
            changed_files=["src/main.py"],
            repo_path=".",
            index=None,
            diff_content="diff --git a/src/main.py b/src/main.py\n@@ -1 +1 @@\n-print('hello')\n+print('world')",
        )

        assert isinstance(result, RetrievalResult)
        assert result.budget_limit == 10000

    async def test_retrieve_empty_changed_files(self):
        engine = RetrievalEngine()
        config = RetrievalConfig(budget=10000, enable_graph_traversal=False)
        engine.configure(config)

        result = await engine.retrieve(
            changed_files=[],
            repo_path=".",
            index=None,
        )

        assert isinstance(result, RetrievalResult)
        assert result.total_tokens >= 0

    async def test_retrieve_with_cache(self):
        engine = RetrievalEngine()
        config = RetrievalConfig(budget=10000, enable_cache=True)
        engine.configure(config)

        result1 = await engine.retrieve(
            changed_files=["test_cache.py"],
            repo_path=".",
            index=None,
            diff_content="test",
        )

        assert isinstance(result1, RetrievalResult)

    async def test_retrieve_with_ranking(self):
        engine = RetrievalEngine()

        class MockRanking:
            async def rank(self, contexts):
                return sorted(contexts, key=lambda c: c.relevance_score, reverse=True)

        engine.set_ranking_engine(MockRanking())
        config = RetrievalConfig(budget=10000, enable_ranking=True, enable_compression=False)
        engine.configure(config)

        result = await engine.retrieve(
            changed_files=[],
            repo_path=".",
            index=None,
        )

        assert isinstance(result, RetrievalResult)

    async def test_retrieve_with_compression(self):
        engine = RetrievalEngine()

        class MockCompression:
            async def compress(self, result, budget):
                pass

        engine.set_compression_engine(MockCompression())
        config = RetrievalConfig(budget=10000, enable_compression=True, enable_ranking=False)
        engine.configure(config)

        result = await engine.retrieve(
            changed_files=[],
            repo_path=".",
            index=None,
        )

        assert isinstance(result, RetrievalResult)

    async def test_retrieve_cache_key_different(self):
        engine = RetrievalEngine()
        config = RetrievalConfig(budget=10000, enable_cache=False)
        engine.configure(config)

        key1 = engine._build_cache_key("repo1", ["a.py"], "diff1")
        key2 = engine._build_cache_key("repo2", ["b.py"], "diff2")

        assert key1 != key2

    async def test_retrieve_cache_key_same(self):
        engine = RetrievalEngine()

        key1 = engine._build_cache_key("repo", ["a.py"], "diff")
        key2 = engine._build_cache_key("repo", ["a.py"], "diff")

        assert key1 == key2

    async def test_configuration(self):
        engine = RetrievalEngine()
        config = RetrievalConfig(
            budget=32000,
            enable_ranking=True,
            enable_compression=True,
            enable_cache=True,
            max_related_files=20,
        )
        engine.configure(config)
        assert engine._config.budget == 32000
        assert engine._config.enable_ranking is True
        assert engine._config.max_related_files == 20

    async def test_retrieve_fallback_on_failure(self):
        engine = RetrievalEngine()
        config = RetrievalConfig(budget=10000, enable_graph_traversal=False)
        engine.configure(config)

        result = await engine.retrieve(
            changed_files=["nonexistent_file.py"],
            repo_path="/nonexistent/path",
            index=None,
        )

        assert isinstance(result, RetrievalResult)
        assert result.total_tokens >= 0

    async def test_build_cache_key(self):
        engine = RetrievalEngine()
        key = engine._build_cache_key("test_repo", ["a.py", "b.py"], "diff")
        assert key.startswith("retrieval:")
        assert len(key) > 20

    async def test_assign_to_result_changed_file(self):
        engine = RetrievalEngine()
        result = RetrievalResult()
        ctx = RetrievedContext(
            file_path="test.py", content="x=1",
            relevance_score=1.0, source="changed_file",
        )
        engine._assign_to_result(result, ctx)
        assert len(result.changed_files) == 1

    async def test_assign_to_result_test(self):
        engine = RetrievalEngine()
        result = RetrievalResult()
        ctx = RetrievedContext(
            file_path="test.py", content="x=1",
            relevance_score=0.9, source="test_graph",
        )
        engine._assign_to_result(result, ctx)
        assert len(result.test_files) == 1

    async def test_assign_to_result_security(self):
        engine = RetrievalEngine()
        result = RetrievalResult()
        ctx = RetrievedContext(
            file_path="auth.py", content="x=1",
            relevance_score=0.6, source="security",
        )
        engine._assign_to_result(result, ctx)
        assert len(result.security_context) == 1

    async def test_assign_to_result_api(self):
        engine = RetrievalEngine()
        result = RetrievalResult()
        ctx = RetrievedContext(
            file_path="routes.py", content="x=1",
            relevance_score=0.7, source="api_endpoint",
        )
        engine._assign_to_result(result, ctx)
        assert len(result.api_endpoints) == 1

    async def test_assign_to_result_db(self):
        engine = RetrievalEngine()
        result = RetrievalResult()
        ctx = RetrievedContext(
            file_path="models.py", content="x=1",
            relevance_score=0.8, source="db_schema",
        )
        engine._assign_to_result(result, ctx)
        assert len(result.db_schemas) == 1

    async def test_all_contexts_aggregation(self):
        result = RetrievalResult()
        result.changed_files.append(RetrievedContext("a.py", "a", 1.0, "changed"))
        result.related_files.append(RetrievedContext("b.py", "b", 0.8, "import"))
        result.test_files.append(RetrievedContext("c.py", "c", 0.9, "test"))
        all_ctx = result.all_contexts()
        assert len(all_ctx) == 3

    async def test_retrieval_result_to_dict(self):
        result = RetrievalResult()
        result.changed_files.append(RetrievedContext(
            file_path="test.py",
            content="hello world",
            relevance_score=1.0,
            source="changed_file",
        ))
        result.total_tokens = 100
        result.budget_used = 0.5

        d = result.to_dict()
        assert d["total_tokens"] == 100
        assert d["budget_used"] == 0.5
        assert len(d["changed_files"]) == 1

    async def test_retrieved_context_content_hash(self):
        ctx = RetrievedContext("a.py", "same content", 0.5, "test")
        ctx2 = RetrievedContext("b.py", "same content", 0.5, "test")
        assert ctx.content_hash == ctx2.content_hash

    async def test_retrieved_context_to_dict_truncation(self):
        long_content = "x" * 2000
        ctx = RetrievedContext("long.py", long_content, 0.5, "test")
        d = ctx.to_dict()
        assert len(d["content"]) <= 500

    async def test_engine_register_retriever(self):
        from app.retrieval.retrievers.base_retriever import BaseRetriever

        class TestRetriever(BaseRetriever):
            @property
            def name(self):
                return "test_retriever"
            async def retrieve(self, config, result):
                return []

        engine = RetrievalEngine()
        engine.register_retriever(TestRetriever())
        assert len(engine._retrievers) > 0

    async def test_config_default_values(self):
        config = RetrievalConfig()
        assert config.budget == 10000
        assert config.enable_ranking is True
        assert config.enable_cache is True
        assert config.enable_fallback is True
