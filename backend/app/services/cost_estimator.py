import uuid
from typing import Optional, Dict, List
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func

from app.models.token_usage import CostBudget


# Cost per 1K tokens by provider (input/output) - updated 2026 pricing
PROVIDER_COST_TABLE = {
    "openai": {"input": 0.0025, "output": 0.01},      # GPT-4o
    "anthropic": {"input": 0.003, "output": 0.015},    # Claude Sonnet
    "gemini": {"input": 0.000125, "output": 0.0005},   # Gemini 2.5 Flash
    "groq": {"input": 0.00059, "output": 0.00079},     # Llama 3.3
    "deepseek": {"input": 0.00014, "output": 0.00028}, # DeepSeek Chat
    "openrouter": {"input": 0.003, "output": 0.015},   # Varies by model
    "azure_openai": {"input": 0.0025, "output": 0.01}, # Same as OpenAI
    "ollama": {"input": 0.0, "output": 0.0},           # Local, free
    "cohere": {"input": 0.0015, "output": 0.002},      # Command R+
    "mistral": {"input": 0.002, "output": 0.006},      # Mistral Large
}


class CostEstimator:
    def get_rates(self, provider: str, model: Optional[str] = None) -> Dict[str, float]:
        normalized = provider.lower().strip()
        return PROVIDER_COST_TABLE.get(normalized, {"input": 0.001, "output": 0.003})

    def estimate(self, provider: str, input_tokens: int, output_tokens: int) -> float:
        rates = self.get_rates(provider)
        return round(
            (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1000, 6
        )

    async def check_and_reserve_budget(
        self, db: AsyncSession, user_id: uuid.UUID, cost_usd: float,
        provider: Optional[str] = None, feature: Optional[str] = None,
    ) -> bool:
        """Atomic check-and-reserve: returns False if budget would be exceeded."""
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = today_start.replace(day=1)

        result = await db.execute(
            select(CostBudget).where(
                CostBudget.user_id == user_id,
                CostBudget.is_active == True,
            )
        )
        budgets = list(result.scalars().all())

        for budget in budgets:
            if budget.provider and budget.provider != provider:
                continue
            if budget.feature and budget.feature != feature:
                continue

            # Reset if period expired
            needs_reset = False
            if budget.budget_type == "daily" and budget.reset_at and budget.reset_at < today_start.isoformat():
                budget.spent_usd = 0.0
                budget.reset_at = today_start.isoformat()
                needs_reset = True
            elif budget.budget_type == "monthly" and budget.reset_at and budget.reset_at < month_start.isoformat():
                budget.spent_usd = 0.0
                budget.reset_at = month_start.isoformat()
                needs_reset = True

            if needs_reset:
                db.add(budget)
                await db.commit()
                await db.refresh(budget)

            # Check if this spend would exceed the budget
            if budget.spent_usd + cost_usd > budget.limit_usd:
                return False

        return True

    async def check_budget(
        self, db: AsyncSession, user_id: uuid.UUID,
        provider: Optional[str] = None, feature: Optional[str] = None,
    ) -> bool:
        """Check if user has any budget remaining."""
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = today_start.replace(day=1)

        result = await db.execute(
            select(CostBudget).where(
                CostBudget.user_id == user_id,
                CostBudget.is_active == True,
            )
        )
        budgets = list(result.scalars().all())

        for budget in budgets:
            if budget.provider and budget.provider != provider:
                continue
            if budget.feature and budget.feature != feature:
                continue

            if budget.budget_type == "daily":
                if budget.reset_at and budget.reset_at < today_start.isoformat():
                    budget.spent_usd = 0.0
                    budget.reset_at = today_start.isoformat()
                    db.add(budget)
                    await db.commit()
                elif budget.spent_usd >= budget.limit_usd:
                    return False

            elif budget.budget_type == "monthly":
                if budget.reset_at and budget.reset_at < month_start.isoformat():
                    budget.spent_usd = 0.0
                    budget.reset_at = month_start.isoformat()
                    db.add(budget)
                    await db.commit()
                elif budget.spent_usd >= budget.limit_usd:
                    return False

        return True

    async def record_spend(
        self, db: AsyncSession, user_id: uuid.UUID, cost_usd: float,
        provider: Optional[str] = None, feature: Optional[str] = None,
    ) -> None:
        """Atomic spend recording - uses SQL-level increment."""
        await db.execute(
            update(CostBudget)
            .where(
                CostBudget.user_id == user_id,
                CostBudget.is_active == True,
                (CostBudget.provider == None) | (CostBudget.provider == provider),
                (CostBudget.feature == None) | (CostBudget.feature == feature),
            )
            .values(spent_usd=CostBudget.spent_usd + cost_usd)
        )
        await db.commit()

    async def get_budgets(self, db: AsyncSession, user_id: uuid.UUID) -> List[CostBudget]:
        result = await db.execute(
            select(CostBudget).where(CostBudget.user_id == user_id)
        )
        return list(result.scalars().all())

    async def create_budget(self, db: AsyncSession, user_id: uuid.UUID, data: dict) -> CostBudget:
        budget = CostBudget(user_id=user_id, **data)
        db.add(budget)
        await db.commit()
        await db.refresh(budget)
        return budget

    async def update_budget(self, db: AsyncSession, budget_id: uuid.UUID, data: dict) -> Optional[CostBudget]:
        budget = await db.get(CostBudget, budget_id)
        if not budget:
            return None
        for key, value in data.items():
            if value is not None:
                setattr(budget, key, value)
        db.add(budget)
        await db.commit()
        await db.refresh(budget)
        return budget

    async def delete_budget(self, db: AsyncSession, budget_id: uuid.UUID) -> bool:
        budget = await db.get(CostBudget, budget_id)
        if not budget:
            return False
        await db.delete(budget)
        await db.commit()
        return True


cost_estimator = CostEstimator()
