import logging
from typing import Optional

from app.retrieval.token_budget_engine import token_budget_engine, TokenBudget
from app.retrieval.models import RetrievalResult

logger = logging.getLogger(__name__)

SECTION_TOKEN_LIMITS = {
    "changed_files": 3000,
    "related_context": 2000,
    "test_files": 1000,
    "config_files": 500,
    "api_endpoints": 500,
    "db_schemas": 500,
    "security_context": 500,
    "impact_context": 500,
    "historical_context": 500,
    "rule_context": 300,
    "documentation_context": 500,
}


class BudgetAllocator:
    def __init__(self):
        self._custom_limits: dict[str, int] = {}

    def set_section_limit(self, section: str, limit: int) -> None:
        self._custom_limits[section] = limit

    def allocate(
        self,
        result: RetrievalResult,
        total_budget: int,
    ) -> TokenBudget:
        budget = token_budget_engine.get_budget(str(total_budget))

        if not budget.allocations:
            budget = TokenBudget(
                total=total_budget,
                allocations=dict(SECTION_TOKEN_LIMITS),
            )

        for section, limit in self._custom_limits.items():
            budget.allocations[section] = limit

        return budget

    def enforce_budget(
        self,
        result: RetrievalResult,
        budget: TokenBudget,
    ) -> None:
        sections = {
            "changed_files": result.changed_files,
            "related_context": result.related_files,
            "test_files": result.test_files,
            "config_files": result.config_files,
            "api_endpoints": result.api_endpoints,
            "db_schemas": result.db_schemas,
            "security_context": result.security_context,
            "impact_context": result.impact_context,
            "historical_context": result.historical_context,
            "rule_context": result.rule_context,
            "documentation_context": result.documentation_context,
        }

        for section_name, ctx_list in sections.items():
            section_limit = budget.allocations.get(section_name, 1000)
            section_tokens = 0
            kept: list = []
            for ctx in ctx_list:
                tokens = len(ctx.content) // 4
                if section_tokens + tokens <= section_limit:
                    section_tokens += tokens
                    kept.append(ctx)

            ctx_list.clear()
            ctx_list.extend(kept)

        result.total_tokens = sum(len(c.content) // 4 for c in result.all_contexts())
        result.budget_used = round(result.total_tokens / max(budget.total, 1), 2)
        result.budget_limit = budget.total


budget_allocator = BudgetAllocator()
