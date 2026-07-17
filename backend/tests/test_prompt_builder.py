"""Comprehensive tests for the Prompt Builder Engine."""

import pytest
import time
from unittest.mock import MagicMock, AsyncMock

from app.prompt_engine.models import (
    ReviewType, RepositorySize, PromptVersion,
    CompiledPrompt, PromptSection, PromptBuildRequest,
    TokenMetadata, ProviderMetadata, PromptExplainability,
)
from app.prompt_engine.builder import PromptBuilder, prompt_builder
from app.prompt_engine.context_ranker import ContextRanker, RankedContext
from app.prompt_engine.token_budget import (
    PromptTokenBudget, detect_repository_size, get_budget_for_size, estimate_tokens
)
from app.prompt_engine.optimizer import PromptOptimizer
from app.prompt_engine.compressor import PromptCompressor
from app.prompt_engine.validator import PromptValidator, ValidationResult
from app.prompt_engine.cache import PromptCache, build_cache_key
from app.prompt_engine.versioning import PromptVersionManager
from app.prompt_engine.observability import PromptObservability
from app.prompt_engine.review_types import get_review_config, REVIEW_TYPE_CONFIGS
from app.prompt_engine.section_builders import ALL_SECTION_BUILDERS


# ============================================================
# Model Tests
# ============================================================

class TestModels:
    def test_review_type_values(self):
        assert ReviewType.PR_REVIEW.value == "pr_review"
        assert ReviewType.SECURITY_REVIEW.value == "security_review"
        assert ReviewType.PERFORMANCE_REVIEW.value == "performance_review"
        assert ReviewType.REPOSITORY_CHAT.value == "repository_chat"

    def test_repository_size_values(self):
        assert RepositorySize.SMALL.value == "small"
        assert RepositorySize.MEDIUM.value == "medium"
        assert RepositorySize.LARGE.value == "large"
        assert RepositorySize.MONOREPO.value == "monorepo"

    def test_compiled_prompt_get_user_messages(self):
        prompt = CompiledPrompt(
            system_prompt="You are a code reviewer.",
            user_prompt="Review this code.",
        )
        messages = prompt.get_user_messages()
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are a code reviewer."
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "Review this code."

    def test_compiled_prompt_get_user_messages_empty(self):
        prompt = CompiledPrompt(system_prompt="System")
        messages = prompt.get_user_messages()
        assert len(messages) == 1
        assert messages[0]["role"] == "system"

    def test_compiled_prompt_explainability_dict(self):
        prompt = CompiledPrompt(
            prompt_version="2.0",
            total_tokens=5000,
            review_type="pr_review",
            token_metadata=TokenMetadata(budget_limit=10000, budget_used=0.5),
            provider_metadata=ProviderMetadata(provider="gemini", model="gemini-2.5-flash"),
            explainability=PromptExplainability(
                context_size=4000,
                files_retrieved=10,
                compression_ratio=0.85,
                sections_included=["repo_summary", "code"],
            ),
        )
        exp_dict = prompt.get_explainability_dict()
        assert exp_dict["prompt_version"] == "2.0"
        assert exp_dict["tokens_used"] == 5000
        assert exp_dict["provider"] == "gemini"
        assert exp_dict["files_retrieved"] == 10
        assert "system_prompt" not in str(exp_dict)

    def test_prompt_build_request_defaults(self):
        request = PromptBuildRequest()
        assert request.review_type == ReviewType.PR_REVIEW
        assert request.repo_size == RepositorySize.MEDIUM
        assert request.token_budget == 10000
        assert request.enable_caching is True


# ============================================================
# Context Ranker Tests
# ============================================================

class TestContextRanker:
    def test_priority_weights(self):
        from app.prompt_engine.context_ranker import PRIORITY_WEIGHTS
        assert PRIORITY_WEIGHTS["changed_file"] == 10
        assert PRIORITY_WEIGHTS["import_graph"] == 9
        assert PRIORITY_WEIGHTS["test_graph"] == 8
        assert PRIORITY_WEIGHTS["config"] == 7
        assert PRIORITY_WEIGHTS["documentation"] == 6

    @pytest.mark.asyncio
    async def test_rank_contexts_no_result(self):
        ranker = ContextRanker()
        result = await ranker.rank_contexts(None, 10000)
        assert result.total_tokens == 0
        assert result.files_count == 0

    @pytest.mark.asyncio
    async def test_rank_contexts_with_contexts(self):
        from app.retrieval.models import RetrievalResult, RetrievedContext

        ranker = ContextRanker()
        result = RetrievalResult()
        result.changed_files.append(
            RetrievedContext("main.py", "x = 1", 1.0, "changed_file")
        )
        result.related_files.append(
            RetrievedContext("utils.py", "y = 2", 0.8, "import_graph")
        )

        ranked = await ranker.rank_contexts(result, 10000)
        assert ranked.files_count == 2
        assert ranked.rankable_contexts[0].file_path == "main.py"


# ============================================================
# Token Budget Tests
# ============================================================

class TestTokenBudget:
    def test_estimate_tokens(self):
        assert estimate_tokens("") == 0
        assert estimate_tokens("1234") == 1
        assert estimate_tokens("12345678") == 2

    def test_detect_repository_size(self):
        assert detect_repository_size(50) == RepositorySize.SMALL
        assert detect_repository_size(500) == RepositorySize.MEDIUM
        assert detect_repository_size(2000) == RepositorySize.LARGE
        assert detect_repository_size(10000) == RepositorySize.MONOREPO

    def test_get_budget_for_size(self):
        assert get_budget_for_size(RepositorySize.SMALL) == 5000
        assert get_budget_for_size(RepositorySize.MEDIUM) == 10000
        assert get_budget_for_size(RepositorySize.LARGE) == 15000
        assert get_budget_for_size(RepositorySize.MONOREPO) == 20000

    def test_budget_manager_allocation(self):
        budget = PromptTokenBudget(RepositorySize.MEDIUM, 10000)
        assert budget.can_fit("repository_summary", 500)
        assert budget.allocate("repository_summary", 500)
        assert not budget.can_fit("repository_summary", 10000)

    def test_budget_manager_usage_ratio(self):
        budget = PromptTokenBudget(RepositorySize.MEDIUM, 10000)
        # Use a real section name that exists in SECTION_ALLOCATIONS
        budget.allocate("relevant_files", 2000)  # MEDIUM relevant_files allocation
        assert budget.get_usage_ratio() == 0.2  # 2000/10000

    def test_budget_manager_build_metadata(self):
        budget = PromptTokenBudget(RepositorySize.MEDIUM, 10000)
        # Use a real section name that exists in SECTION_ALLOCATIONS
        budget.allocate("relevant_files", 2000)  # MEDIUM relevant_files allocation
        metadata = budget.build_token_metadata()
        assert metadata.total_tokens == 2000
        assert metadata.budget_limit == 10000
        assert metadata.budget_used == 0.2

    def test_budget_total_enforcement(self):
        """Test that total budget is enforced across sections.

        Uses LARGE repo size where sum of base allocations (11800) > default 10000,
        so after filling several sections, remaining total budget can be exceeded.
        """
        budget = PromptTokenBudget(RepositorySize.LARGE, 10000)
        # Fill several sections up to their LARGE allocations
        budget.allocate("relevant_files", 3000)
        budget.allocate("relevant_code", 2500)
        budget.allocate("repository_summary", 800)
        budget.allocate("architecture_summary", 600)
        budget.allocate("repository_rules", 500)
        budget.allocate("coding_conventions", 500)
        budget.allocate("test_files", 800)
        budget.allocate("static_analysis", 700)
        # Total used: 9400
        # security_context fits (500 <= 500 per-section, 9900 <= 10000 total)
        budget.allocate("security_context", 500)
        # Total used: 9900, remaining: 100
        # Now review_context should be rejected by TOTAL budget (not per-section)
        # review_context allocation for LARGE: 400. But 9900 + 400 = 10300 > 10000
        assert not budget.can_fit("review_context", 400)

    def test_budget_unknown_section_gets_default(self):
        """Test that unknown sections get a default allocation."""
        budget = PromptTokenBudget(RepositorySize.MEDIUM, 10000)
        allocation = budget.get_allocation("unknown_section")
        assert allocation == 200  # DEFAULT_SECTION_ALLOCATION * scale


# ============================================================
# Optimizer Tests
# ============================================================

class TestPromptOptimizer:
    @pytest.mark.asyncio
    async def test_optimize_empty(self):
        optimizer = PromptOptimizer()
        budget = PromptTokenBudget(RepositorySize.MEDIUM, 10000)
        result = await optimizer.optimize({}, budget)
        assert result == {}

    @pytest.mark.asyncio
    async def test_optimize_fits_budget(self):
        optimizer = PromptOptimizer()
        budget = PromptTokenBudget(RepositorySize.MEDIUM, 10000)
        sections = {
            "system_instructions": PromptSection("system_instructions", "You are a reviewer.", 10),
            "code": PromptSection("code", "x = 1", 1),
        }
        result = await optimizer.optimize(sections, budget)
        assert "system_instructions" in result
        assert "code" in result


# ============================================================
# Compressor Tests
# ============================================================

class TestPromptCompressor:
    @pytest.mark.asyncio
    async def test_compress_empty(self):
        compressor = PromptCompressor()
        result = await compressor.compress_sections({}, 10000)
        assert result == {}

    @pytest.mark.asyncio
    async def test_compress_removes_duplicates(self):
        compressor = PromptCompressor()
        sections = {
            "section1": PromptSection("section1", "Same content here.", 5),
            "section2": PromptSection("section2", "Same content here.", 5),
        }
        result = await compressor.compress_sections(sections, 10000)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_compress_removes_empty_lines(self):
        compressor = PromptCompressor()
        content = "Line 1\n\n\n\nLine 2"
        sections = {"test": PromptSection("test", content, 10)}
        result = await compressor.compress_sections(sections, 10000)
        assert "\n\n\n\n" not in result["test"].content


# ============================================================
# Validator Tests
# ============================================================

class TestPromptValidator:
    @pytest.mark.asyncio
    async def test_validate_valid_prompt(self):
        validator = PromptValidator()
        prompt = CompiledPrompt(
            prompt_id="test_123",
            system_prompt="System",
            user_prompt="User",
            total_tokens=100,
            cache_key="abc123",
        )
        request = PromptBuildRequest(provider="gemini")
        result = await validator.validate(prompt, request)
        assert result.valid

    @pytest.mark.asyncio
    async def test_validate_missing_system_prompt(self):
        validator = PromptValidator()
        prompt = CompiledPrompt(
            prompt_id="test_123",
            system_prompt="",
            user_prompt="User",
            total_tokens=100,
        )
        request = PromptBuildRequest(provider="gemini")
        result = await validator.validate(prompt, request)
        assert not result.valid
        assert "Missing system prompt" in result.errors

    @pytest.mark.asyncio
    async def test_validate_exceeds_provider_limit(self):
        validator = PromptValidator()
        prompt = CompiledPrompt(
            prompt_id="test_123",
            system_prompt="System",
            user_prompt="User",
            total_tokens=200000,
        )
        request = PromptBuildRequest(provider="openai")
        result = await validator.validate(prompt, request)
        assert not result.valid
        assert any("exceeds" in e for e in result.errors)


# ============================================================
# Cache Tests
# ============================================================

class TestPromptCache:
    @pytest.mark.asyncio
    async def test_cache_miss(self):
        cache = PromptCache()
        result = await cache.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        cache = PromptCache()
        prompt = CompiledPrompt(system_prompt="Test", user_prompt="Content")
        await cache.set("key1", prompt)
        result = await cache.get("key1")
        assert result is not None
        assert result.system_prompt == "Test"

    @pytest.mark.asyncio
    async def test_cache_invalidation(self):
        cache = PromptCache()
        prompt = CompiledPrompt(system_prompt="Test")
        await cache.set("key1", prompt)
        assert await cache.invalidate("key1")
        result = await cache.get("key1")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_max_size(self):
        cache = PromptCache(max_size=2)
        await cache.set("k1", CompiledPrompt(system_prompt="1"))
        await cache.set("k2", CompiledPrompt(system_prompt="2"))
        await cache.set("k3", CompiledPrompt(system_prompt="3"))
        assert await cache.get("k1") is None
        assert await cache.get("k2") is not None

    @pytest.mark.asyncio
    async def test_cache_stats(self):
        cache = PromptCache()
        await cache.set("k1", CompiledPrompt(system_prompt="1"))
        await cache.get("k1")
        await cache.get("k2")
        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1

    def test_build_cache_key(self):
        key1 = build_cache_key("pr_review", "repo1", "diff1", "gemini", "model1", 10000)
        key2 = build_cache_key("pr_review", "repo1", "diff1", "gemini", "model1", 10000)
        key3 = build_cache_key("pr_review", "repo2", "diff1", "gemini", "model1", 10000)
        assert key1 == key2
        assert key1 != key3


# ============================================================
# Versioning Tests
# ============================================================

class TestPromptVersionManager:
    @pytest.mark.asyncio
    async def test_register_and_get_version(self):
        vm = PromptVersionManager()
        prompt = CompiledPrompt(
            system_prompt="Test",
            provider_metadata=ProviderMetadata(provider="gemini"),
            token_metadata=TokenMetadata(budget_limit=10000),
        )
        await vm.register_version("template1", "1.0", prompt)
        record = await vm.get_version("template1", "1.0")
        assert record is not None
        assert record.version == "1.0"

    @pytest.mark.asyncio
    async def test_list_versions(self):
        vm = PromptVersionManager()
        prompt = CompiledPrompt(
            system_prompt="Test",
            provider_metadata=ProviderMetadata(provider="gemini"),
            token_metadata=TokenMetadata(budget_limit=10000),
        )
        await vm.register_version("template1", "1.0", prompt)
        await vm.register_version("template1", "2.0", prompt)
        versions = await vm.list_versions("template1")
        assert len(versions) == 2

    @pytest.mark.asyncio
    async def test_rollback(self):
        vm = PromptVersionManager()
        prompt = CompiledPrompt(
            system_prompt="Test",
            provider_metadata=ProviderMetadata(provider="gemini"),
            token_metadata=TokenMetadata(budget_limit=10000),
        )
        await vm.register_version("template1", "1.0", prompt)
        await vm.register_version("template1", "2.0", prompt)
        assert await vm.rollback("template1", "1.0")
        active = await vm.get_active_version("template1")
        assert active == "1.0"


# ============================================================
# Observability Tests
# ============================================================

class TestPromptObservability:
    @pytest.mark.asyncio
    async def test_record_and_get_metrics(self):
        obs = PromptObservability()
        prompt = CompiledPrompt(
            prompt_id="test_123",
            total_tokens=5000,
            token_metadata=TokenMetadata(budget_limit=10000),
            explainability=PromptExplainability(files_retrieved=10),
        )
        request = PromptBuildRequest(review_type=ReviewType.PR_REVIEW, provider="gemini")
        await obs.record_build(prompt, request, 100.0)

        metrics = await obs.get_metrics("test_123")
        assert metrics is not None
        assert metrics["total_tokens"] == 5000

    @pytest.mark.asyncio
    async def test_aggregate_metrics(self):
        obs = PromptObservability()
        prompt = CompiledPrompt(
            prompt_id="test_1",
            total_tokens=5000,
            token_metadata=TokenMetadata(budget_limit=10000),
            explainability=PromptExplainability(files_retrieved=5),
        )
        request = PromptBuildRequest(review_type=ReviewType.PR_REVIEW, provider="gemini")
        await obs.record_build(prompt, request, 100.0)

        agg = await obs.get_aggregate_metrics(provider="gemini")
        assert agg["count"] == 1
        assert agg["avg_tokens"] == 5000


# ============================================================
# Review Types Tests
# ============================================================

class TestReviewTypes:
    def test_all_review_types_have_config(self):
        for review_type in ReviewType:
            config = get_review_config(review_type)
            assert "system_instruction" in config
            assert "analysis_focus" in config
            assert "output_format" in config

    def test_pr_review_config(self):
        config = get_review_config(ReviewType.PR_REVIEW)
        assert "Revora AI" in config["system_instruction"]
        assert "code review" in config["system_instruction"].lower()

    def test_security_review_config(self):
        config = get_review_config(ReviewType.SECURITY_REVIEW)
        assert "security" in config["system_instruction"].lower()


# ============================================================
# Section Builders Tests
# ============================================================

class TestSectionBuilders:
    def test_all_builders_registered(self):
        assert len(ALL_SECTION_BUILDERS) == 14

    def test_builder_names_unique(self):
        names = [b.name for b in ALL_SECTION_BUILDERS]
        assert len(names) == len(set(names))

    @pytest.mark.asyncio
    async def test_system_instructions_builder(self):
        from app.prompt_engine.section_builders import SystemInstructionsBuilder
        builder = SystemInstructionsBuilder()
        request = PromptBuildRequest(review_type=ReviewType.PR_REVIEW)
        section = await builder.safe_build(request, {})
        assert section is not None
        assert "Revora AI" in section.content

    @pytest.mark.asyncio
    async def test_repository_summary_builder_no_data(self):
        from app.prompt_engine.section_builders import RepositorySummaryBuilder
        builder = RepositorySummaryBuilder()
        request = PromptBuildRequest(intelligence_data={})
        section = await builder.safe_build(request, {})
        assert section is None

    @pytest.mark.asyncio
    async def test_output_format_builder(self):
        from app.prompt_engine.section_builders import OutputFormatBuilder
        builder = OutputFormatBuilder()
        request = PromptBuildRequest(review_type=ReviewType.PR_REVIEW)
        section = await builder.safe_build(request, {})
        assert section is not None
        assert "Markdown" in section.content

    def test_file_extension_detection(self):
        """Test that .tsx and .jsx are detected correctly (Bug 5)."""
        from app.prompt_engine.section_builders import RelevantCodeBuilder
        builder = RelevantCodeBuilder()
        assert builder._detect_language("Component.tsx") == "tsx"
        assert builder._detect_language("Component.jsx") == "jsx"
        assert builder._detect_language("utils.ts") == "typescript"
        assert builder._detect_language("utils.js") == "javascript"
        assert builder._detect_language("app.py") == "python"
        assert builder._detect_language("main.go") == "go"


# ============================================================
# Builder Integration Tests
# ============================================================

class TestPromptBuilder:
    @pytest.mark.asyncio
    async def test_compile_backward_compat(self):
        builder = PromptBuilder()
        prompt = await builder.compile(
            repo_summary="A Python project",
            architecture_summary="MVC",
            conventions="PEP 8",
            rules=["No print statements"],
            diff_content="diff --git a/main.py\n+print('hello')",
        )
        assert isinstance(prompt, CompiledPrompt)
        assert prompt.system_prompt
        assert prompt.user_prompt
        assert prompt.total_tokens > 0

    @pytest.mark.asyncio
    async def test_compile_with_new_interface(self):
        builder = PromptBuilder()
        request = PromptBuildRequest(
            review_type=ReviewType.SECURITY_REVIEW,
            diff_content="test diff",
            provider="openai",
            model="gpt-4o",
        )
        prompt = await builder.compile(**request.__dict__)
        assert isinstance(prompt, CompiledPrompt)
        assert prompt.review_type == "security_review"

    @pytest.mark.asyncio
    async def test_compile_generates_unique_ids(self):
        builder = PromptBuilder()
        prompt1 = await builder.compile(diff_content="diff1")
        prompt2 = await builder.compile(diff_content="diff2")
        assert prompt1.prompt_id != prompt2.prompt_id

    @pytest.mark.asyncio
    async def test_compile_includes_all_sections(self):
        builder = PromptBuilder()
        prompt = await builder.compile(
            review_type=ReviewType.PR_REVIEW,
            diff_content="test diff",
            conventions="PEP 8",
            rules=["Rule 1"],
        )
        assert "system_instructions" in [s for s in prompt.sections.keys()] or prompt.system_prompt
        assert "output_format" in [s for s in prompt.sections.keys()]

    @pytest.mark.asyncio
    async def test_compile_backward_compat_messages(self):
        builder = PromptBuilder()
        prompt = await builder.compile(diff_content="test")
        messages = prompt.get_user_messages()
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    @pytest.mark.asyncio
    async def test_compile_all_review_types(self):
        builder = PromptBuilder()
        for review_type in ReviewType:
            prompt = await builder.compile(
                review_type=review_type,
                diff_content="test diff",
            )
            assert isinstance(prompt, CompiledPrompt)
            assert prompt.review_type == review_type.value
            assert prompt.total_tokens > 0

    @pytest.mark.asyncio
    async def test_compile_with_intelligence_data(self):
        """Test that intelligence_data is properly forwarded (Bug 3/4 fix)."""
        builder = PromptBuilder()
        prompt = await builder.compile(
            intelligence_data={
                "languages": [{"name": "Python"}],
                "frameworks": [{"name": "FastAPI"}],
                "architecture": {"pattern": "MVC"},
                "file_count": 150,
                "total_lines": 50000,
            },
            diff_content="test",
        )
        assert "Python" in prompt.user_prompt
        assert "FastAPI" in prompt.user_prompt

    @pytest.mark.asyncio
    async def test_compile_explainability(self):
        builder = PromptBuilder()
        prompt = await builder.compile(diff_content="test")
        exp = prompt.get_explainability_dict()
        assert "prompt_version" in exp
        assert "tokens_used" in exp
        assert "provider" in exp
        assert "system_prompt" not in str(exp)

    @pytest.mark.asyncio
    async def test_compile_caching(self):
        builder = PromptBuilder()
        prompt1 = await builder.compile(
            diff_content="test",
            enable_caching=True,
        )
        prompt2 = await builder.compile(
            diff_content="test",
            enable_caching=True,
        )
        assert prompt1.cache_key == prompt2.cache_key

    @pytest.mark.asyncio
    async def test_compile_token_budget(self):
        builder = PromptBuilder()
        prompt = await builder.compile(
            diff_content="test",
            token_budget=5000,
        )
        assert prompt.token_metadata.budget_limit == 5000

    @pytest.mark.asyncio
    async def test_compile_build_time(self):
        builder = PromptBuilder()
        prompt = await builder.compile(diff_content="test")
        assert prompt.build_time_ms >= 0
        assert prompt.created_at > 0

    @pytest.mark.asyncio
    async def test_compile_mixed_legacy_and_new_kwargs(self):
        """Test that mixed legacy and new kwargs don't crash (Bug 1 fix)."""
        builder = PromptBuilder()
        # This should NOT crash - should filter to only PromptBuildRequest fields
        prompt = await builder.compile(
            review_type=ReviewType.PR_REVIEW,
            diff_content="test",
            provider="openai",
        )
        assert isinstance(prompt, CompiledPrompt)
        assert prompt.review_type == "pr_review"

    @pytest.mark.asyncio
    async def test_compile_compression_ratio(self):
        """Test that compression ratio is conventional (Bug 9 fix)."""
        builder = PromptBuilder()
        prompt = await builder.compile(diff_content="test")
        # With no compression, ratio should be 0.0
        assert 0.0 <= prompt.token_metadata.compression_ratio <= 1.0

