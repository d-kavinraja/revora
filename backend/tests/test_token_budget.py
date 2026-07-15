import pytest
from app.retrieval.token_budget_engine import TokenBudgetEngine, TokenBudget, PRESET_BUDGETS


@pytest.fixture
def budget_engine():
    return TokenBudgetEngine()


class TestTokenBudgetEngine:
    async def test_preset_budgets(self, budget_engine):
        for label in ["4K", "8K", "16K", "32K", "64K", "128K"]:
            budget = budget_engine.get_budget(label)
            assert budget.total == PRESET_BUDGETS[label]
            assert len(budget.allocations) > 0

    async def test_custom_budget(self, budget_engine):
        budget = budget_engine.get_budget("10K")
        assert budget.total == 10000

    async def test_invalid_budget_defaults(self, budget_engine):
        budget = budget_engine.get_budget("unknown")
        assert budget.total == 16000

    async def test_token_allocations_valid(self, budget_engine):
        budget = budget_engine.get_budget("16K")
        total_allocated = sum(budget.allocations.values())
        assert total_allocated <= budget.total

    async def test_custom_allocation(self, budget_engine):
        budget_engine.set_custom_allocation("16K", {
            "changed_files": 5000, "related_context": 5000,
            "output_buffer": 2000,
        })
        budget = budget_engine.get_budget("16K")
        assert budget.allocations["changed_files"] == 5000
        assert budget.allocations["related_context"] == 5000

    async def test_budget_can_allocate(self):
        budget = TokenBudget(total=1000, allocations={"test": 500})
        assert budget.can_allocate("test", 300) is True
        assert budget.can_allocate("test", 600) is False
        assert budget.can_allocate("other", 1500) is False

    async def test_budget_allocate(self):
        budget = TokenBudget(total=1000, allocations={"test": 500})
        assert budget.allocate("test", 300) is True
        assert budget.used["test"] == 300
        assert budget.allocate("test", 300) is False
        assert budget.used["test"] == 300

    async def test_budget_remaining(self):
        budget = TokenBudget(total=1000, allocations={"a": 500, "b": 500})
        budget.allocate("a", 200)
        assert budget.remaining == 800
        budget.allocate("b", 300)
        assert budget.remaining == 500

    async def test_budget_reset(self):
        budget = TokenBudget(total=1000, allocations={"a": 500})
        budget.allocate("a", 200)
        assert budget.used["a"] == 200
        budget.reset()
        assert budget.used == {}

    async def test_estimate_allocations_small(self, budget_engine):
        budget = budget_engine.get_budget("2000")
        assert budget.total == 2000

    async def test_estimate_allocations_large(self, budget_engine):
        budget = budget_engine.get_budget("100K")
        assert budget.total == 100000

    async def test_supported_budgets_list(self):
        assert "4K" in TokenBudgetEngine.SUPPORTED_BUDGETS
        assert "128K" in TokenBudgetEngine.SUPPORTED_BUDGETS
