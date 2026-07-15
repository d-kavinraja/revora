import pytest
from app.retrieval.fallback import RetrievalFallback, retrieval_fallback


class TestRetrievalFallback:
    async def test_initial_strategy(self):
        fb = RetrievalFallback()
        assert fb.current_strategy == "graph_retrieval"

    async def test_escalate_cycle(self):
        fb = RetrievalFallback()
        assert fb.current_strategy == "graph_retrieval"

        fb.escalate()
        assert fb.current_strategy == "knowledge_base"

        fb.escalate()
        assert fb.current_strategy == "static_analysis"

        fb.escalate()
        assert fb.current_strategy == "pr_diff_only"

        fb.escalate()
        assert fb.current_strategy == "graceful_failure"

    async def test_has_fallback(self):
        fb = RetrievalFallback()
        assert fb.has_fallback is True

        for _ in range(4):
            fb.escalate()

        assert fb.has_fallback is False

    async def test_reset(self):
        fb = RetrievalFallback()
        fb.escalate()
        fb.escalate()
        assert fb.current_strategy == "static_analysis"

        fb.reset()
        assert fb.current_strategy == "graph_retrieval"
        assert fb.used_strategies == []

    async def test_used_strategies_tracked(self):
        fb = RetrievalFallback()
        fb.escalate()
        fb.escalate()
        assert "knowledge_base" in fb.used_strategies
        assert "static_analysis" in fb.used_strategies

    async def test_should_use_methods(self):
        fb = RetrievalFallback()

        assert fb.should_use_graph() is True
        assert fb.should_use_knowledge_base() is False

        fb.escalate()
        assert fb.should_use_graph() is False
        assert fb.should_use_knowledge_base() is True

        fb.escalate()
        assert fb.should_use_static_analysis() is True

        fb.escalate()
        assert fb.should_use_diff_only() is True

        fb.escalate()
        assert fb.is_failed() is True

    async def test_minimal_result(self):
        result = RetrievalFallback.create_minimal_result("diff content")
        assert result["fallback"] is True
        assert result["strategy"] == "pr_diff_only"
        assert result["diff_content"] == "diff content"

    async def test_minimal_result_no_diff(self):
        result = RetrievalFallback.create_minimal_result()
        assert result["fallback"] is True
        assert result["diff_content"] == ""

    async def test_escalate_past_end(self):
        fb = RetrievalFallback()
        for _ in range(5):
            fb.escalate()
        assert fb.current_strategy == "graceful_failure"
        fb.escalate()
        assert fb.current_strategy == "graceful_failure"

    async def test_global_instance(self):
        assert retrieval_fallback.current_strategy == "graph_retrieval"
        retrieval_fallback.reset()
