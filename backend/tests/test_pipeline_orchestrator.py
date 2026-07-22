"""Integration tests for the Review Pipeline orchestrator.

Tests the end-to-end flow through all 10 pipeline stages with
mocked external dependencies. Each stage is tested independently
and in the full pipeline context.
"""

import sys
import pytest
import uuid
from unittest.mock import MagicMock, AsyncMock, patch, ANY
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Pre-load mock modules to satisfy import dependencies
# ---------------------------------------------------------------------------
# litellm cannot be installed (requires Rust/Cargo on Windows).
# We inject a mock before any app.* import triggers app.ai.llm -> litellm.
_mock_litellm = MagicMock()
_mock_litellm.completion = AsyncMock()
sys.modules['litellm'] = _mock_litellm

# Also pre-load app.pipeline so patch.object() can resolve its attributes
import app.pipeline.orchestrator as _orch_mod  # noqa: E402
# ---------------------------------------------------------------------------


# =============================================================================
# Helper fixtures
# =============================================================================

@pytest.fixture
def sample_review_id():
    return uuid.uuid4()


@pytest.fixture
def sample_diff():
    return (
        "diff --git a/main.py b/main.py\n"
        "index abc..def 100644\n"
        "--- a/main.py\n"
        "+++ b/main.py\n"
        "@@ -1,3 +1,4 @@\n"
        " def hello():\n"
        "-    print('old')\n"
        "+    print('new')\n"
        "+    return 42\n"
    )


@pytest.fixture
def sample_llm_response():
    # Lazy import to avoid app.orchestrator.__init__ -> litellm chain
    from app.orchestrator.models import LLMResponse
    return LLMResponse(
        content="## Summary\nLooks good.",
        provider="gemini",
        model="gemini-2.0-flash",
        input_tokens=500,
        output_tokens=150,
        latency_ms=1200.0,
        estimated_cost_usd=0.002,
    )


@pytest.fixture
def sample_verification_result():
    from app.verification.models import VerificationResult, VerifiedFinding
    return VerificationResult(
        findings=[
            VerifiedFinding(
                id="finding-1",
                file_path="main.py",
                line_number=5,
                issue_type="bug",
                severity="medium",
                description="Return value not checked",
                suggestion="Check return value",
                confidence=0.85,
                is_verified=True,
            )
        ],
        total_findings=1,
        verified_count=1,
        rejected_count=0,
        avg_confidence=0.85,
    )


@pytest.fixture
def sample_review_summary():
    from app.github_review.models import GitHubReviewSummary, GitHubReviewComment
    return GitHubReviewSummary(
        body="## Review Summary\nLooks good overall.",
        event="COMMENT",
        risk_score="low",
        comments=[
            GitHubReviewComment(
                path="main.py",
                body="Consider checking the return value.",
                line=5,
            )
        ],
        stats={"verified_findings": 1, "total_findings": 1},
    )


@pytest.fixture
def mock_compiled_prompt():
    from app.prompt_engine.models import CompiledPrompt
    prompt = CompiledPrompt(
        prompt_id="test_prompt_123",
        system_prompt="You are a code reviewer.",
        user_prompt="## Output Format\n\nReview this PR.",
        total_tokens=150,
        cache_key="abc123",
    )
    prompt.review_type = "pr_review"
    return prompt


# =============================================================================
# Pipeline patching fixture
# =============================================================================

@pytest.fixture(autouse=True)
def pipeline_mocks():
    """Mock all external dependencies used by the pipeline.

    Must import the module first so patch() can resolve the dotted paths.
    """
    # Import FIRST so patch can resolve app.pipeline.orchestrator.*
    import app.pipeline.orchestrator as orch_mod

    patches = {
        "git_service": patch.object(orch_mod, "GitService"),
        "intelligence": patch.object(orch_mod, "intelligence_engine"),
        "indexer": patch.object(orch_mod, "repository_indexer"),
        "knowledge": patch.object(orch_mod, "knowledge_store"),
        "retrieval": patch.object(orch_mod, "retrieval_engine"),
        "llm": patch.object(orch_mod, "llm_orchestrator"),
        "verification": patch.object(orch_mod, "verification_engine"),
        "review_gen": patch.object(orch_mod, "github_review_generator"),
        "github_client": patch.object(orch_mod, "github_client"),
        "sse": patch.object(orch_mod, "SSEEmitter"),
        "db_session": patch.object(orch_mod, "AsyncSessionLocal"),
    }

    mocks = {}
    for name, p in patches.items():
        mock_obj = p.start()
        mocks[name] = mock_obj
        if hasattr(mock_obj, "return_value"):
            mock_obj.return_value = MagicMock()

    yield mocks

    for p in patches.values():
        p.stop()


# =============================================================================
# Helper: configure pipeline mocks for success path
# =============================================================================

def configure_success_mocks(
    mocks,
    sample_diff,
    sample_llm_response,
    sample_verification_result,
    sample_review_summary,
    mock_compiled_prompt,
):
    """Configure all mocks for a successful pipeline execution."""
    # GitService.clone_repository returns a path (async method)
    mocks["git_service"].clone_repository = AsyncMock(return_value="/tmp/test-repo")
    mocks["git_service"].cleanup_repository = AsyncMock()

    # Intelligence result
    intelligence_mock = MagicMock()
    intelligence_mock.to_dict.return_value = {
        "languages": [{"name": "Python", "percentage": 100.0}],
        "frameworks": [{"name": "FastAPI"}],
        "architecture": {"pattern": "microservices"},
    }
    intelligence_mock.languages = []
    intelligence_mock.frameworks = []
    intelligence_mock.architecture = MagicMock()
    intelligence_mock.architecture.pattern = "microservices"
    mocks["intelligence"].analyze = AsyncMock(return_value=intelligence_mock)

    # Repository index
    index_mock = MagicMock()
    index_mock.nodes = []
    index_mock.edges = []
    mocks["indexer"].build_index = AsyncMock(return_value=index_mock)

    # Knowledge store
    mocks["knowledge"].load_or_generate_conventions = AsyncMock(
        return_value="PEP 8 style"
    )
    mocks["knowledge"].load_rules = AsyncMock(
        return_value=["No print statements"]
    )

    # Retrieval result
    retrieval_result = MagicMock()
    retrieval_result.total_tokens = 500
    retrieval_result.fallback_used = None
    retrieval_result.all_contexts.return_value = []
    mocks["retrieval"].configure = MagicMock()
    mocks["retrieval"].retrieve = AsyncMock(return_value=retrieval_result)

    # LLM orchestrator
    mocks["llm"].complete = AsyncMock(return_value=sample_llm_response)
    mocks["llm"].get_total_usage = MagicMock(return_value={
        "total_prompts": 10,
        "total_tokens": 5000,
    })

    # Verification
    mocks["verification"].verify = AsyncMock(return_value=sample_verification_result)

    # Review generation
    mocks["review_gen"].generate = AsyncMock(return_value=sample_review_summary)

    # GitHub Client (async methods)
    mocks["github_client"].create_pr_review = AsyncMock(return_value=MagicMock())

    # SSE Emitter
    mock_sse_instance = MagicMock()
    mocks["sse"].return_value = mock_sse_instance
    mock_sse_instance.emit = AsyncMock()
    mock_sse_instance.emit_log = AsyncMock()
    mock_sse_instance.emit_error = AsyncMock()

    # DB session
    mock_db_context = MagicMock()
    mocks["db_session"].return_value = mock_db_context
    mock_db_context.__aenter__ = AsyncMock(return_value=mock_db_context)
    mock_db_context.__aexit__ = AsyncMock(return_value=None)

    # DB queries
    mock_execute = MagicMock()
    mock_db_context.execute = AsyncMock(return_value=mock_execute)
    mock_scalars = MagicMock()
    mock_execute.scalars.return_value = mock_scalars
    mock_scalars.first.return_value = MagicMock()
    mock_scalars.first.return_value.id = uuid.uuid4()
    mock_db_context.commit = AsyncMock()
    mock_db_context.refresh = AsyncMock()
    mock_db_context.add = MagicMock()

    return mocks


# =============================================================================
# Tests
# =============================================================================

class TestPipelineFullExecution:
    """Full pipeline end-to-end tests."""

    @pytest.mark.asyncio
    async def test_execute_full_success(
        self,
        pipeline_mocks,
        sample_review_id,
        sample_diff,
        sample_llm_response,
        sample_verification_result,
        sample_review_summary,
        mock_compiled_prompt,
    ):
        """Happy path: all stages complete successfully."""
        from app.sse.events import EventType
        from app.pipeline.orchestrator import ReviewPipeline

        mocks = configure_success_mocks(
            pipeline_mocks, sample_diff, sample_llm_response,
            sample_verification_result, sample_review_summary,
            mock_compiled_prompt,
        )
        pipeline = ReviewPipeline()

        result = await pipeline.execute(
            review_id=sample_review_id,
            installation_id=12345,
            owner="test-owner",
            repo_name="test-repo",
            pr_number=42,
            pr_title="Fix bug",
            pr_description="Fixes a critical bug",
            head_sha="abc123def456",
            diff_content=sample_diff,
            user_id=str(uuid.uuid4()),
            provider="gemini",
            model="gemini-2.0-flash",
            clone_url="https://github.com/test-owner/test-repo.git",
            token="ghp_test_token",
        )

        assert result["status"] == "success"
        assert "duration_ms" in result
        assert result["metrics"]["provider"] == "gemini"
        assert result["metrics"]["input_tokens"] == 500
        assert result["metrics"]["output_tokens"] == 150

        # Verify clone was attempted
        mocks["git_service"].clone_repository.assert_called_once()

        # Verify intelligence and indexing ran
        mocks["intelligence"].analyze.assert_called_once_with("/tmp/test-repo")
        mocks["indexer"].build_index.assert_called_once_with("/tmp/test-repo")

        # Verify knowledge was retrieved
        mocks["knowledge"].load_or_generate_conventions.assert_called_once()
        mocks["knowledge"].load_rules.assert_called_once()

        # Verify retrieval ran
        mocks["retrieval"].configure.assert_called_once()
        mocks["retrieval"].retrieve.assert_called_once()

        # Verify LLM was called
        mocks["llm"].complete.assert_called_once()

        # Verify verification ran
        mocks["verification"].verify.assert_called_once()

        # Verify review was generated and published
        mocks["review_gen"].generate.assert_called_once()
        mocks["github_client"].create_pr_review.assert_called_once()

        # Verify pipeline completed event (use precise EventType constant)
        mocks["sse"].return_value.emit.assert_any_call(
            "completed", "completed", EventType.REVIEW_COMPLETE, metrics=ANY
        )

    @pytest.mark.asyncio
    async def test_execute_without_clone(
        self,
        pipeline_mocks,
        sample_review_id,
        sample_diff,
        sample_llm_response,
        sample_verification_result,
        sample_review_summary,
        mock_compiled_prompt,
    ):
        """Pipeline degrades gracefully when no clone URL is provided."""
        from app.pipeline.orchestrator import ReviewPipeline

        mocks = configure_success_mocks(
            pipeline_mocks, sample_diff, sample_llm_response,
            sample_verification_result, sample_review_summary,
            mock_compiled_prompt,
        )
        pipeline = ReviewPipeline()

        result = await pipeline.execute(
            review_id=sample_review_id,
            installation_id=12345,
            owner="test-owner",
            repo_name="test-repo",
            pr_number=42,
            pr_title="Fix bug",
            pr_description="",
            head_sha="abc123",
            diff_content=sample_diff,
            user_id=str(uuid.uuid4()),
            provider="gemini",
            clone_url=None,  # No clone URL
            token=None,
        )

        assert result["status"] == "success"
        # Clone should not be called
        mocks["git_service"].clone_repository.assert_not_called()
        # Intelligence and indexing should be skipped
        mocks["intelligence"].analyze.assert_not_called()
        mocks["indexer"].build_index.assert_not_called()
        # Retrieval should be skipped (no index)
        mocks["retrieval"].retrieve.assert_not_called()
        # But LLM and verification should still run
        mocks["llm"].complete.assert_called_once()
        mocks["verification"].verify.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_clone_failure(
        self,
        pipeline_mocks,
        sample_review_id,
        sample_diff,
        sample_llm_response,
        sample_verification_result,
        sample_review_summary,
        mock_compiled_prompt,
    ):
        """Clone failure should gracefully skip intelligence and indexing."""
        from app.pipeline.orchestrator import ReviewPipeline

        mocks = configure_success_mocks(
            pipeline_mocks, sample_diff, sample_llm_response,
            sample_verification_result, sample_review_summary,
            mock_compiled_prompt,
        )
        # Make clone fail
        mocks["git_service"].clone_repository = AsyncMock(
            side_effect=Exception("Clone failed: permission denied")
        )
        pipeline = ReviewPipeline()

        result = await pipeline.execute(
            review_id=sample_review_id,
            installation_id=12345,
            owner="test-owner",
            repo_name="test-repo",
            pr_number=42,
            pr_title="Fix bug",
            pr_description="",
            head_sha="abc123",
            diff_content=sample_diff,
            user_id=str(uuid.uuid4()),
            provider="gemini",
            clone_url="https://github.com/test-owner/test-repo.git",
            token="ghp_test_token",
        )

        assert result["status"] == "success"
        # Intelligence and indexing should be skipped due to clone failure
        mocks["intelligence"].analyze.assert_not_called()
        mocks["indexer"].build_index.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_intelligence_failure(
        self,
        pipeline_mocks,
        sample_review_id,
        sample_diff,
        sample_llm_response,
        sample_verification_result,
        sample_review_summary,
        mock_compiled_prompt,
    ):
        """Intelligence failure should return empty data and continue."""
        from app.pipeline.orchestrator import ReviewPipeline

        mocks = configure_success_mocks(
            pipeline_mocks, sample_diff, sample_llm_response,
            sample_verification_result, sample_review_summary,
            mock_compiled_prompt,
        )
        # Make intelligence fail
        mocks["intelligence"].analyze = AsyncMock(
            side_effect=Exception("Analysis error")
        )
        pipeline = ReviewPipeline()

        result = await pipeline.execute(
            review_id=sample_review_id,
            installation_id=12345,
            owner="test-owner",
            repo_name="test-repo",
            pr_number=42,
            pr_title="Fix bug",
            pr_description="",
            head_sha="abc123",
            diff_content=sample_diff,
            user_id=str(uuid.uuid4()),
            provider="gemini",
            clone_url="https://github.com/test-owner/test-repo.git",
            token="ghp_test_token",
        )

        assert result["status"] == "success"
        # Indexing should still run
        mocks["indexer"].build_index.assert_called_once()
        # Pipeline continues with empty intelligence data

    @pytest.mark.asyncio
    async def test_execute_indexing_failure(
        self,
        pipeline_mocks,
        sample_review_id,
        sample_diff,
        sample_llm_response,
        sample_verification_result,
        sample_review_summary,
        mock_compiled_prompt,
    ):
        """Indexing failure should skip context retrieval but continue."""
        from app.pipeline.orchestrator import ReviewPipeline

        mocks = configure_success_mocks(
            pipeline_mocks, sample_diff, sample_llm_response,
            sample_verification_result, sample_review_summary,
            mock_compiled_prompt,
        )
        # Make indexing fail
        mocks["indexer"].build_index = AsyncMock(
            side_effect=Exception("Indexing error")
        )
        pipeline = ReviewPipeline()

        result = await pipeline.execute(
            review_id=sample_review_id,
            installation_id=12345,
            owner="test-owner",
            repo_name="test-repo",
            pr_number=42,
            pr_title="Fix bug",
            pr_description="",
            head_sha="abc123",
            diff_content=sample_diff,
            user_id=str(uuid.uuid4()),
            provider="gemini",
            clone_url="https://github.com/test-owner/test-repo.git",
            token="ghp_test_token",
        )

        assert result["status"] == "success"
        # Retrieval should be skipped (no index)
        mocks["retrieval"].retrieve.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_retrieval_failure(
        self,
        pipeline_mocks,
        sample_review_id,
        sample_diff,
        sample_llm_response,
        sample_verification_result,
        sample_review_summary,
        mock_compiled_prompt,
    ):
        """Retrieval failure should build prompt without context."""
        from app.pipeline.orchestrator import ReviewPipeline

        mocks = configure_success_mocks(
            pipeline_mocks, sample_diff, sample_llm_response,
            sample_verification_result, sample_review_summary,
            mock_compiled_prompt,
        )
        # Make retrieval fail
        mocks["retrieval"].retrieve = AsyncMock(
            side_effect=Exception("Retrieval error")
        )
        pipeline = ReviewPipeline()

        result = await pipeline.execute(
            review_id=sample_review_id,
            installation_id=12345,
            owner="test-owner",
            repo_name="test-repo",
            pr_number=42,
            pr_title="Fix bug",
            pr_description="",
            head_sha="abc123",
            diff_content=sample_diff,
            user_id=str(uuid.uuid4()),
            provider="gemini",
            clone_url="https://github.com/test-owner/test-repo.git",
            token="ghp_test_token",
        )

        assert result["status"] == "success"
        # LLM should still be called (prompt built without retrieval context)
        mocks["llm"].complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_llm_failure(
        self,
        pipeline_mocks,
        sample_review_id,
        sample_diff,
        sample_llm_response,
        sample_verification_result,
        sample_review_summary,
        mock_compiled_prompt,
    ):
        """LLM failure should cause pipeline to return error.

        Prompt building and LLM stages are critical - pipeline cannot
        proceed without them.
        """
        from app.pipeline.orchestrator import ReviewPipeline

        mocks = configure_success_mocks(
            pipeline_mocks, sample_diff, sample_llm_response,
            sample_verification_result, sample_review_summary,
            mock_compiled_prompt,
        )
        # Make LLM fail
        mocks["llm"].complete = AsyncMock(
            side_effect=Exception("LLM provider unavailable")
        )
        pipeline = ReviewPipeline()

        result = await pipeline.execute(
            review_id=sample_review_id,
            installation_id=12345,
            owner="test-owner",
            repo_name="test-repo",
            pr_number=42,
            pr_title="Fix bug",
            pr_description="",
            head_sha="abc123",
            diff_content=sample_diff,
            user_id=str(uuid.uuid4()),
            provider="gemini",
            clone_url="https://github.com/test-owner/test-repo.git",
            token="ghp_test_token",
        )

        assert result["status"] == "failed"
        assert "LLM provider unavailable" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_prompt_building_failure(
        self,
        pipeline_mocks,
        sample_review_id,
        sample_diff,
        sample_llm_response,
        sample_verification_result,
        sample_review_summary,
        mock_compiled_prompt,
    ):
        """Prompt building failure (critical stage) should fail the pipeline."""
        from app.pipeline.orchestrator import ReviewPipeline
        from app.prompt_engine.builder import prompt_builder

        mocks = configure_success_mocks(
            pipeline_mocks, sample_diff, sample_llm_response,
            sample_verification_result, sample_review_summary,
            mock_compiled_prompt,
        )
        # Patch the prompt builder to fail
        with patch.object(prompt_builder, "compile", side_effect=Exception("Prompt build failed")):
            pipeline = ReviewPipeline()

            result = await pipeline.execute(
                review_id=sample_review_id,
                installation_id=12345,
                owner="test-owner",
                repo_name="test-repo",
                pr_number=42,
                pr_title="Fix bug",
                pr_description="",
                head_sha="abc123",
                diff_content=sample_diff,
                user_id=str(uuid.uuid4()),
                provider="gemini",
                clone_url="https://github.com/test-owner/test-repo.git",
                token="ghp_test_token",
            )

        assert result["status"] == "failed"
        assert "Prompt build failed" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_verification_failure(
        self,
        pipeline_mocks,
        sample_review_id,
        sample_diff,
        sample_llm_response,
        sample_verification_result,
        sample_review_summary,
        mock_compiled_prompt,
    ):
        """Verification failure should return empty result and continue."""
        from app.pipeline.orchestrator import ReviewPipeline

        mocks = configure_success_mocks(
            pipeline_mocks, sample_diff, sample_llm_response,
            sample_verification_result, sample_review_summary,
            mock_compiled_prompt,
        )
        # Make verification fail
        mocks["verification"].verify = AsyncMock(
            side_effect=Exception("Verification error")
        )
        pipeline = ReviewPipeline()

        result = await pipeline.execute(
            review_id=sample_review_id,
            installation_id=12345,
            owner="test-owner",
            repo_name="test-repo",
            pr_number=42,
            pr_title="Fix bug",
            pr_description="",
            head_sha="abc123",
            diff_content=sample_diff,
            user_id=str(uuid.uuid4()),
            provider="gemini",
            clone_url="https://github.com/test-owner/test-repo.git",
            token="ghp_test_token",
        )

        assert result["status"] == "success"
        # Pipeline continues with empty verification result

    @pytest.mark.asyncio
    async def test_execute_publish_failure(
        self,
        pipeline_mocks,
        sample_review_id,
        sample_diff,
        sample_llm_response,
        sample_verification_result,
        sample_review_summary,
        mock_compiled_prompt,
    ):
        """GitHub publish failure should not fail the pipeline."""
        from app.pipeline.orchestrator import ReviewPipeline

        mocks = configure_success_mocks(
            pipeline_mocks, sample_diff, sample_llm_response,
            sample_verification_result, sample_review_summary,
            mock_compiled_prompt,
        )
        # Make GitHub publish fail
        mocks["github_client"].create_pr_review = AsyncMock(
            side_effect=Exception("GitHub API error")
        )
        pipeline = ReviewPipeline()

        result = await pipeline.execute(
            review_id=sample_review_id,
            installation_id=12345,
            owner="test-owner",
            repo_name="test-repo",
            pr_number=42,
            pr_title="Fix bug",
            pr_description="",
            head_sha="abc123",
            diff_content=sample_diff,
            user_id=str(uuid.uuid4()),
            provider="gemini",
            clone_url="https://github.com/test-owner/test-repo.git",
            token="ghp_test_token",
        )

        assert result["status"] == "success"
        # Pipeline should have caught the publish error gracefully

    @pytest.mark.asyncio
    async def test_execute_provider_forwarding(
        self,
        pipeline_mocks,
        sample_review_id,
        sample_diff,
        sample_llm_response,
        sample_verification_result,
        sample_review_summary,
        mock_compiled_prompt,
    ):
        """Provider parameter should be forwarded through stages."""
        from app.pipeline.orchestrator import ReviewPipeline

        mocks = configure_success_mocks(
            pipeline_mocks, sample_diff, sample_llm_response,
            sample_verification_result, sample_review_summary,
            mock_compiled_prompt,
        )
        pipeline = ReviewPipeline()

        # Use a non-default provider
        result = await pipeline.execute(
            review_id=sample_review_id,
            installation_id=12345,
            owner="test-owner",
            repo_name="test-repo",
            pr_number=42,
            pr_title="Fix bug",
            pr_description="",
            head_sha="abc123",
            diff_content=sample_diff,
            user_id=str(uuid.uuid4()),
            provider="openai",
            model="gpt-4o",
            clone_url="https://github.com/test-owner/test-repo.git",
            token="ghp_test_token",
        )

        assert result["status"] == "success"
        # LLM should have been called with the correct provider
        call_kwargs = mocks["llm"].complete.call_args.kwargs
        assert call_kwargs["preferred_provider"] == "openai"

    @pytest.mark.asyncio
    async def test_execute_db_save_failure(
        self,
        pipeline_mocks,
        sample_review_id,
        sample_diff,
        sample_llm_response,
        sample_verification_result,
        sample_review_summary,
        mock_compiled_prompt,
    ):
        """DB save failure should not fail the pipeline."""
        from app.pipeline.orchestrator import ReviewPipeline

        mocks = configure_success_mocks(
            pipeline_mocks, sample_diff, sample_llm_response,
            sample_verification_result, sample_review_summary,
            mock_compiled_prompt,
        )
        # Make DB save fail
        mocks["db_session"].return_value.__aenter__.return_value.commit = AsyncMock(
            side_effect=Exception("DB connection lost")
        )
        pipeline = ReviewPipeline()

        result = await pipeline.execute(
            review_id=sample_review_id,
            installation_id=12345,
            owner="test-owner",
            repo_name="test-repo",
            pr_number=42,
            pr_title="Fix bug",
            pr_description="",
            head_sha="abc123",
            diff_content=sample_diff,
            user_id=str(uuid.uuid4()),
            provider="gemini",
            clone_url="https://github.com/test-owner/test-repo.git",
            token="ghp_test_token",
        )

        assert result["status"] == "success"


class TestPipelineIndividualStages:
    """Individual stage tests with direct stage calls."""

    @pytest.mark.asyncio
    async def test_stage_clone_skipped_no_url(self, pipeline_mocks):
        """Clone stage returns None when no URL is given."""
        from app.pipeline.orchestrator import ReviewPipeline

        pipeline = ReviewPipeline()
        emitter = MagicMock()
        emitter.emit = AsyncMock()

        result = await pipeline._stage_clone(emitter, None, None)

        assert result is None
        emitter.emit.assert_any_call(
            "cloning_repository", "skipped", ANY, message="No clone URL provided"
        )

    @pytest.mark.asyncio
    async def test_stage_clone_success(self, pipeline_mocks):
        """Clone stage returns repo path on success."""
        from app.pipeline.orchestrator import ReviewPipeline

        pipeline = ReviewPipeline()
        emitter = MagicMock()
        emitter.emit = AsyncMock()
        pipeline_mocks["git_service"].clone_repository = AsyncMock(
            return_value="/tmp/test-repo"
        )

        result = await pipeline._stage_clone(
            emitter, "https://github.com/owner/repo.git", "token123"
        )

        assert result == "/tmp/test-repo"

    @pytest.mark.asyncio
    async def test_stage_intelligence_skipped_no_repo(self, pipeline_mocks):
        """Intelligence stage returns empty dict when no repo path."""
        from app.pipeline.orchestrator import ReviewPipeline

        pipeline = ReviewPipeline()
        emitter = MagicMock()
        emitter.emit = AsyncMock()

        result = await pipeline._stage_intelligence(emitter, None)

        assert result == {}

    @pytest.mark.asyncio
    async def test_stage_indexing_skipped_no_repo(self, pipeline_mocks):
        """Indexing stage returns None when no repo path."""
        from app.pipeline.orchestrator import ReviewPipeline

        pipeline = ReviewPipeline()
        emitter = MagicMock()
        emitter.emit = AsyncMock()

        result = await pipeline._stage_indexing(emitter, None)

        assert result is None

    @pytest.mark.asyncio
    async def test_stage_retrieval_skipped_no_index(self, pipeline_mocks):
        """Retrieval stage returns None when no index."""
        from app.pipeline.orchestrator import ReviewPipeline

        pipeline = ReviewPipeline()
        emitter = MagicMock()
        emitter.emit = AsyncMock()

        result = await pipeline._stage_retrieval(
            emitter, None, "diff content", repo_id=None
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_stage_prompt_forwards_provider(
        self, pipeline_mocks, sample_diff
    ):
        """Prompt building stage forwards provider to prompt_builder.compile()."""
        from app.pipeline.orchestrator import ReviewPipeline

        pipeline = ReviewPipeline()
        emitter = MagicMock()
        emitter.emit = AsyncMock()

        retrieval_result = MagicMock()
        retrieval_result.total_tokens = 500
        retrieval_result.fallback_used = None

        prompt = await pipeline._stage_prompt(
            emitter=emitter,
            intelligence_data={"languages": [{"name": "Python"}]},
            conventions="PEP 8",
            rules=["No prints"],
            diff_content=sample_diff,
            retrieval_result=retrieval_result,
            provider="openai",
        )

        assert prompt is not None
        assert prompt.total_tokens > 0
        # Verify the provider was forwarded to the compiled prompt
        assert prompt.provider_metadata.provider == "openai"

    @pytest.mark.asyncio
    async def test_stage_retrieval_parses_changed_files(
        self, pipeline_mocks, sample_diff
    ):
        """Retrieval stage parses diff to extract changed files."""
        from app.pipeline.orchestrator import ReviewPipeline

        # Set up the retrieve mock as AsyncMock so await works
        pipeline_mocks["retrieval"].retrieve = AsyncMock(
            return_value=MagicMock(total_tokens=100, fallback_used=None)
        )
        pipeline_mocks["retrieval"].configure = MagicMock()

        pipeline = ReviewPipeline()
        emitter = MagicMock()
        emitter.emit = AsyncMock()

        index_mock = MagicMock()
        index_mock.nodes = []
        index_mock.edges = []

        await pipeline._stage_retrieval(
            emitter, index_mock, sample_diff, repo_id=uuid.uuid4()
        )

        # Verify retrieval was called with the changed file from the diff
        call_args = pipeline_mocks["retrieval"].retrieve.await_args
        assert call_args is not None
        changed_files_arg = call_args.args[0]
        assert "main.py" in changed_files_arg

    @pytest.mark.asyncio
    async def test_stage_prompt_builds_valid_prompt(
        self, pipeline_mocks, sample_diff
    ):
        """Prompt building stage produces a valid compiled prompt."""
        from app.pipeline.orchestrator import ReviewPipeline

        pipeline = ReviewPipeline()
        emitter = MagicMock()
        emitter.emit = AsyncMock()

        prompt = await pipeline._stage_prompt(
            emitter=emitter,
            intelligence_data={},
            conventions="",
            rules=[],
            diff_content=sample_diff,
            retrieval_result=None,
            provider="gemini",
        )

        assert prompt is not None
        assert prompt.system_prompt
        assert "Revora AI" in prompt.system_prompt
        assert prompt.total_tokens > 0

        # Should produce valid messages for LLM
        messages = prompt.get_user_messages()
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
