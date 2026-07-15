import pytest
from app.retrieval.models import RetrievedContext, RetrievalResult, RetrievalConfig
from app.retrieval.retrievers.base_retriever import BaseRetriever
from app.retrieval.retrievers.rule_retriever import RuleRetriever
from app.retrieval.retrievers.historical_retriever import HistoricalRetriever
from app.retrieval.retrievers.documentation_retriever import DocumentationRetriever
from app.indexing.models import RepositoryIndex, CodeGraph, GraphNode, GraphEdge


class TestBaseRetriever:
    async def test_safe_retrieve_catches_exceptions(self):
        class FailingRetriever(BaseRetriever):
            @property
            def name(self):
                return "failing"

            async def retrieve(self, config, result):
                raise RuntimeError("Intentional failure")

        retriever = FailingRetriever()
        config = RetrievalConfig()
        result = RetrievalResult()

        contexts = await retriever.safe_retrieve(config, result)
        assert contexts == []

    async def test_safe_retrieve_success(self):
        class SuccessRetriever(BaseRetriever):
            @property
            def name(self):
                return "success"

            async def retrieve(self, config, result):
                return [RetrievedContext(
                    file_path="test.py",
                    content="x=1",
                    relevance_score=0.5,
                    source="test",
                )]

        retriever = SuccessRetriever()
        config = RetrievalConfig()
        result = RetrievalResult()

        contexts = await retriever.safe_retrieve(config, result)
        assert len(contexts) == 1
        assert contexts[0].file_path == "test.py"


class TestRuleRetriever:
    async def test_no_repo_id_returns_empty(self):
        retriever = RuleRetriever()
        config = RetrievalConfig()
        result = RetrievalResult()
        contexts = await retriever.safe_retrieve(config, result)
        assert contexts == []


class TestHistoricalRetriever:
    async def test_disabled_returns_empty(self):
        retriever = HistoricalRetriever()
        config = RetrievalConfig(enable_historical_context=False)
        result = RetrievalResult()
        contexts = await retriever.safe_retrieve(config, result)
        assert contexts == []

    async def test_no_repo_id_returns_empty(self):
        retriever = HistoricalRetriever()
        config = RetrievalConfig(enable_historical_context=True)
        result = RetrievalResult()
        contexts = await retriever.safe_retrieve(config, result)
        assert contexts == []


class TestDocumentationRetriever:
    async def test_no_changed_files_graceful(self):
        retriever = DocumentationRetriever()
        config = RetrievalConfig()
        result = RetrievalResult()
        result._repo_path = "."
        result._changed_file_paths = []
        contexts = await retriever.safe_retrieve(config, result)
        assert isinstance(contexts, list)


class TestRetrieverEdgeCases:
    async def test_empty_config(self):
        class MinimalRetriever(BaseRetriever):
            @property
            def name(self):
                return "minimal"

            async def retrieve(self, config, result):
                return []

        retriever = MinimalRetriever()
        config = RetrievalConfig()
        result = RetrievalResult()
        contexts = await retriever.safe_retrieve(config, result)
        assert contexts == []

    async def test_large_number_of_retrievers_error_isolation(self):
        from app.retrieval.retrievers.import_retriever import ImportRetriever
        from app.retrieval.retrievers.call_graph_retriever import CallGraphRetriever
        from app.retrieval.retrievers.module_retriever import ModuleRetriever

        retrievers = [ImportRetriever(), CallGraphRetriever(), ModuleRetriever()]
        config = RetrievalConfig()
        result = RetrievalResult()
        result._index = None
        result._repo_path = "."
        result._changed_file_paths = []

        for retriever in retrievers:
            contexts = await retriever.safe_retrieve(config, result)
            assert isinstance(contexts, list)
