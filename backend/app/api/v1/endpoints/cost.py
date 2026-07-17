from typing import Optional
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.token_manager import token_manager
from app.services.cost_estimator import cost_estimator

router = APIRouter()


def _parse_period(period: str):
    now = datetime.now(timezone.utc)
    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        start = now - timedelta(days=7)
    elif period == "month":
        start = now - timedelta(days=30)
    else:
        start = now - timedelta(days=30)
    return start, now


@router.get("")
async def get_cost(
    period: str = Query("month", pattern="^(today|week|month)$"),
    provider: Optional[str] = None,
    model: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get cost details for a period, optionally filtered by provider/model."""
    start, end = _parse_period(period)
    breakdown = await token_manager.get_cost_breakdown(db, current_user.id, start, end)

    result = {
        "period": period,
        "total_cost_usd": breakdown["total_cost_usd"],
        "total_tokens": breakdown["total_tokens"],
        "by_provider": breakdown["by_provider"],
        "by_model": breakdown["by_model"],
        "by_feature": breakdown["by_feature"],
    }

    if provider:
        result["provider_cost"] = breakdown["by_provider"].get(provider, 0)
    if model:
        result["model_cost"] = breakdown["by_model"].get(model, 0)

    return result


@router.get("/estimate")
async def estimate_cost(
    provider: str,
    input_tokens: int = Query(..., ge=0),
    output_tokens: int = Query(..., ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Estimate cost for a given provider and token counts."""
    estimated = cost_estimator.estimate(provider, input_tokens, output_tokens)
    rates = cost_estimator.get_rates(provider)
    return {
        "provider": provider,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": estimated,
        "rates_per_1k": rates,
    }

