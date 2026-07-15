import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

PRESET_BUDGETS = {
    "4K": 4000,
    "8K": 8000,
    "16K": 16000,
    "32K": 32000,
    "64K": 64000,
    "128K": 128000,
}

DEFAULT_ALLOCATIONS = {
    "4K": {
        "system": 200, "repo_summary": 200, "architecture": 100,
        "rules": 100, "changed_files": 1200, "related_context": 1000,
        "static_analysis": 200, "output_buffer": 1000,
    },
    "8K": {
        "system": 300, "repo_summary": 300, "architecture": 200,
        "rules": 200, "changed_files": 2500, "related_context": 2000,
        "static_analysis": 300, "output_buffer": 1200,
    },
    "16K": {
        "system": 500, "repo_summary": 500, "architecture": 500,
        "rules": 300, "changed_files": 4000, "related_context": 5000,
        "tests": 1000, "static_analysis": 500, "output_buffer": 1700,
    },
    "32K": {
        "system": 1000, "repo_summary": 1000, "architecture": 1000,
        "rules": 500, "changed_files": 8000, "related_context": 10000,
        "tests": 2000, "static_analysis": 1000, "dependencies": 2000,
        "output_buffer": 3500,
    },
    "64K": {
        "system": 2000, "repo_summary": 2000, "architecture": 2000,
        "rules": 1000, "changed_files": 15000, "related_context": 20000,
        "tests": 4000, "static_analysis": 2000, "dependencies": 5000,
        "impact_analysis": 3000, "output_buffer": 5000,
    },
    "128K": {
        "system": 4000, "repo_summary": 4000, "architecture": 3000,
        "rules": 2000, "changed_files": 30000, "related_context": 40000,
        "tests": 8000, "static_analysis": 4000, "dependencies": 10000,
        "impact_analysis": 8000, "historical_context": 3000,
        "security_context": 2000, "documentation": 3000,
        "output_buffer": 12000,
    },
}


@dataclass
class TokenBudget:
    total: int
    allocations: dict[str, int] = field(default_factory=dict)
    used: dict[str, int] = field(default_factory=dict)

    @property
    def remaining(self) -> int:
        return self.total - sum(self.used.values())

    def can_allocate(self, section: str, tokens: int) -> bool:
        max_allowed = self.allocations.get(section, self.total)
        current_used = self.used.get(section, 0)
        return (current_used + tokens) <= max_allowed and (
            current_used + tokens + sum(self.used.values()) - current_used
        ) <= self.total

    def allocate(self, section: str, tokens: int) -> bool:
        if not self.can_allocate(section, tokens):
            return False
        self.used[section] = self.used.get(section, 0) + tokens
        return True

    def reset(self) -> None:
        self.used = {}


class TokenBudgetEngine:
    SUPPORTED_BUDGETS = sorted(PRESET_BUDGETS.keys(), key=lambda k: PRESET_BUDGETS[k])

    def __init__(self):
        self._custom_allocations: dict[str, dict[str, int]] = {}

    def get_budget(self, budget_label: str = "16K") -> TokenBudget:
        total = self._resolve_total(budget_label)
        allocations = self._get_allocations(budget_label)
        return TokenBudget(total=total, allocations=dict(allocations))

    def _resolve_total(self, budget_label: str) -> int:
        label_upper = budget_label.upper()
        if label_upper in PRESET_BUDGETS:
            return PRESET_BUDGETS[label_upper]

        try:
            val = int(budget_label.replace("K", "").replace("k", ""))
            return val * 1000
        except (ValueError, TypeError):
            logger.warning(f"Unknown budget label '{budget_label}', defaulting to 16K")
            return 16000

    def _get_allocations(self, budget_label: str) -> dict[str, int]:
        label_upper = budget_label.upper()

        if label_upper in self._custom_allocations:
            return self._custom_allocations[label_upper]

        exact = DEFAULT_ALLOCATIONS.get(label_upper)
        if exact:
            return dict(exact)

        total = self._resolve_total(budget_label)
        return self._estimate_allocations(total)

    def _estimate_allocations(self, total: int) -> dict[str, int]:
        if total <= 4000:
            return dict(DEFAULT_ALLOCATIONS["4K"])
        elif total <= 8000:
            return dict(DEFAULT_ALLOCATIONS["8K"])
        elif total <= 16000:
            return dict(DEFAULT_ALLOCATIONS["16K"])
        elif total <= 32000:
            return dict(DEFAULT_ALLOCATIONS["32K"])
        elif total <= 64000:
            return dict(DEFAULT_ALLOCATIONS["64K"])
        else:
            return dict(DEFAULT_ALLOCATIONS["128K"])

    def set_custom_allocation(self, budget_label: str, allocations: dict[str, int]) -> None:
        self._custom_allocations[budget_label.upper()] = allocations
        logger.info(f"Custom allocation set for {budget_label}: {allocations}")

    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def truncate_to_budget(self, text: str, max_tokens: int) -> str:
        max_chars = max_tokens * 4
        if len(text) <= max_chars:
            return text
        truncated = text[:max_chars]
        last_newline = truncated.rfind("\n")
        if last_newline > max_chars * 0.8:
            truncated = truncated[:last_newline]
        return truncated + "\n... [truncated]"


token_budget_engine = TokenBudgetEngine()
