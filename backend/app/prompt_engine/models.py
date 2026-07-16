import time
import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional, List
from enum import Enum


class ReviewType(str, Enum):
    """Supported review types for prompt building."""
    PR_REVIEW = "pr_review"
    REPO_REVIEW = "repo_review"
    SECURITY_REVIEW = "security_review"
    PERFORMANCE_REVIEW = "performance_review"
    ARCHITECTURE_REVIEW = "architecture_review"
    TESTING_REVIEW = "testing_review"
    DOCUMENTATION_REVIEW = "documentation_review"
    PATCH_GENERATION = "patch_generation"
    EXPLAINABILITY = "explainability"
    REPOSITORY_CHAT = "repository_chat"


class RepositorySize(str, Enum):
    """Repository size categories for strategy selection."""
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    MONOREPO = "monorepo"
    ENTERPRISE = "enterprise"


class PromptVersion(str, Enum):
    """Prompt version identifiers."""
    V1 = "1.0"
    V2 = "2.0"
    V3 = "3.0"


@dataclass
class PromptSection:
    """A single section within a compiled prompt."""
    name: str
    content: str
    token_count: int = 0
    version: str = "1.0"
    priority: int = 0
    compressed: bool = False
    source_files: list[str] = field(default_factory=list)


@dataclass
class TokenMetadata:
    """Token usage metadata for a compiled prompt."""
    total_tokens: int = 0
    budget_limit: int = 10000
    budget_used: float = 0.0
    section_tokens: Dict[str, int] = field(default_factory=dict)
    compression_ratio: float = 1.0
    estimated_cost_usd: float = 0.0


@dataclass
class ProviderMetadata:
    """Provider and model metadata for a compiled prompt."""
    provider: str = ""
    model: str = ""
    context_window: int = 0
    max_output_tokens: int = 0
    supports_streaming: bool = True
    supports_function_calling: bool = False


@dataclass
class PromptExplainability:
    """User-facing explainability metadata. Does NOT expose system prompt or internal instructions."""
    prompt_version: str = ""
    tokens_used: int = 0
    context_size: int = 0
    files_retrieved: int = 0
    compression_ratio: float = 1.0
    selected_provider: str = ""
    selected_model: str = ""
    review_type: str = ""
    sections_included: list[str] = field(default_factory=list)
    budget_allocation: Dict[str, int] = field(default_factory=dict)


@dataclass
class PromptBuildRequest:
    """Input specification for the Prompt Builder Engine."""
    review_type: ReviewType = ReviewType.PR_REVIEW
    repo_id: Optional[str] = None
    repo_path: str = "."
    repo_size: RepositorySize = RepositorySize.MEDIUM
    diff_content: str = ""
    retrieval_result: object = None
    intelligence_data: dict = field(default_factory=dict)
    conventions: str = ""
    rules: list[str] = field(default_factory=list)
    static_analysis: str = ""
    provider: str = "gemini"
    model: str = ""
    token_budget: int = 10000
    pr_number: int = 0
    pr_title: str = ""
    pr_description: str = ""
    issue_context: str = ""
    organization_rules: list[str] = field(default_factory=list)
    enable_caching: bool = True
    enable_compression: bool = True
    enable_versioning: bool = True


@dataclass
class CompiledPrompt:
    """Output of the Prompt Builder Engine. Backward-compatible with LLM Orchestrator."""
    version: str = "2.0"
    prompt_id: str = ""
    prompt_version: str = ""
    review_type: str = ""
    sections: Dict[str, PromptSection] = field(default_factory=dict)
    system_prompt: str = ""
    user_prompt: str = ""
    total_tokens: int = 0
    cache_key: str = ""
    token_metadata: TokenMetadata = field(default_factory=TokenMetadata)
    provider_metadata: ProviderMetadata = field(default_factory=ProviderMetadata)
    explainability: PromptExplainability = field(default_factory=PromptExplainability)
    created_at: float = 0.0
    build_time_ms: float = 0.0

    def get_user_messages(self) -> list[dict]:
        """Backward-compatible message format for LLM Orchestrator."""
        messages = [{"role": "system", "content": self.system_prompt}]
        if self.user_prompt:
            messages.append({"role": "user", "content": self.user_prompt})
        return messages

    def get_explainability_dict(self) -> dict:
        """User-facing metadata. Does NOT expose system_prompt or internal instructions."""
        return {
            "prompt_version": self.prompt_version,
            "tokens_used": self.total_tokens,
            "context_size": self.explainability.context_size,
            "files_retrieved": self.explainability.files_retrieved,
            "compression_ratio": self.explainability.compression_ratio,
            "provider": self.provider_metadata.provider,
            "model": self.provider_metadata.model,
            "review_type": self.review_type,
            "sections": self.explainability.sections_included,
            "budget": self.token_metadata.budget_limit,
            "budget_used": self.token_metadata.budget_used,
        }
