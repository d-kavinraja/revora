"""Token budget management for prompt building.

Manages token allocation across prompt sections based on repository size
and review type. Extends the retrieval engine's budget system.
"""

import logging
from typing import Dict, Optional
from app.prompt_engine.models import RepositorySize, TokenMetadata

logger = logging.getLogger(__name__)

CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Rough token estimation: 4 chars per token."""
    return len(text) // CHARS_PER_TOKEN


SECTION_ALLOCATIONS = {
    RepositorySize.SMALL: {
        "system_instructions": 500,
        "repository_summary": 300,
        "architecture_summary": 200,
        "repository_rules": 200,
        "coding_conventions": 200,
        "relevant_files": 1000,
        "relevant_code": 800,
        "review_context": 200,
        "output_format": 300,
    },
    RepositorySize.MEDIUM: {
        "system_instructions": 500,
        "repository_summary": 500,
        "architecture_summary": 400,
        "repository_rules": 400,
        "coding_conventions": 400,
        "relevant_files": 2000,
        "relevant_code": 1500,
        "test_files": 500,
        "static_analysis": 500,
        "review_context": 300,
        "output_format": 400,
    },
    RepositorySize.LARGE: {
        "system_instructions": 500,
        "repository_summary": 800,
        "architecture_summary": 600,
        "repository_rules": 500,
        "coding_conventions": 500,
        "relevant_files": 3000,
        "relevant_code": 2500,
        "test_files": 800,
        "static_analysis": 700,
        "security_context": 500,
        "review_context": 400,
        "output_format": 500,
    },
    RepositorySize.MONOREPO: {
        "system_instructions": 500,
        "repository_summary": 1000,
        "architecture_summary": 800,
        "repository_rules": 600,
        "coding_conventions": 600,
        "relevant_files": 3500,
        "relevant_code": 3000,
        "test_files": 1000,
        "static_analysis": 800,
        "security_context": 600,
        "impact_context": 500,
        "review_context": 500,
        "output_format": 600,
    },
    RepositorySize.ENTERPRISE: {
        "system_instructions": 500,
        "repository_summary": 1500,
        "architecture_summary": 1000,
        "repository_rules": 800,
        "coding_conventions": 800,
        "relevant_files": 4000,
        "relevant_code": 3500,
        "test_files": 1200,
        "static_analysis": 1000,
        "security_context": 800,
        "impact_context": 700,
        "review_context": 600,
        "output_format": 700,
    },
}

# Default allocation for sections not in the allocation map
DEFAULT_SECTION_ALLOCATION = 200


class PromptTokenBudget:
    """Manages token allocation across prompt sections.

    Enforces both per-section limits and total budget.
    """

    def __init__(self, repo_size: RepositorySize = RepositorySize.MEDIUM, total_budget: int = 10000):
        self.repo_size = repo_size
        self.total_budget = total_budget
        self.allocations = SECTION_ALLOCATIONS.get(repo_size, SECTION_ALLOCATIONS[RepositorySize.MEDIUM])
        self.used: Dict[str, int] = {}

    def get_allocation(self, section_name: str) -> int:
        """Get the token allocation for a section."""
        allocation = self.allocations.get(section_name, DEFAULT_SECTION_ALLOCATION)
        scaled = int(allocation * (self.total_budget / 10000))
        return scaled

    def can_fit(self, section_name: str, tokens: int) -> bool:
        """Check if a section can fit within its allocation AND total budget."""
        allocation = self.get_allocation(section_name)
        current = self.used.get(section_name, 0)
        within_section = current + tokens <= allocation
        within_total = self.get_used_tokens() + tokens <= self.total_budget
        return within_section and within_total

    def allocate(self, section_name: str, tokens: int) -> bool:
        """Allocate tokens for a section. Returns True if successful."""
        if self.can_fit(section_name, tokens):
            self.used[section_name] = self.used.get(section_name, 0) + tokens
            return True
        return False

    def get_used_tokens(self) -> int:
        """Get total tokens used across all sections."""
        return sum(self.used.values())

    def get_remaining_tokens(self) -> int:
        """Get remaining tokens in the budget."""
        return max(0, self.total_budget - self.get_used_tokens())

    def get_usage_ratio(self) -> float:
        """Get the ratio of used tokens to total budget."""
        if self.total_budget == 0:
            return 0.0
        return self.get_used_tokens() / self.total_budget

    def build_token_metadata(self) -> TokenMetadata:
        """Build TokenMetadata from current state."""
        total_used = self.get_used_tokens()
        return TokenMetadata(
            total_tokens=total_used,
            budget_limit=self.total_budget,
            budget_used=self.get_usage_ratio(),
            section_tokens=dict(self.used),
            compression_ratio=1.0,
            estimated_cost_usd=0.0,
        )


def detect_repository_size(file_count: int) -> RepositorySize:
    """Detect repository size from file count."""
    if file_count < 100:
        return RepositorySize.SMALL
    elif file_count < 1000:
        return RepositorySize.MEDIUM
    elif file_count < 5000:
        return RepositorySize.LARGE
    else:
        return RepositorySize.MONOREPO


def get_budget_for_size(repo_size: RepositorySize) -> int:
    """Get recommended token budget for repository size."""
    budget_map = {
        RepositorySize.SMALL: 5000,
        RepositorySize.MEDIUM: 10000,
        RepositorySize.LARGE: 15000,
        RepositorySize.MONOREPO: 20000,
        RepositorySize.ENTERPRISE: 30000,
    }
    return budget_map.get(repo_size, 10000)
