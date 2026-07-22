from typing import List, Optional
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.token_manager import token_manager
from app.services.cost_estimator import cost_estimator
from app.schemas.usage import (
    UsageSummary, UsageRecordRead,
    CostBudgetCreate, CostBudgetUpdate, CostBudgetRead, DailyCost,
)

router = APIRouter()


def _parse_period(period: str, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None):
    if period == "custom" and start_date and end_date:
        return start_date, end_date
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


@router.get("/summary", response_model=UsageSummary)
async def get_usage_summary(
    period: str = Query("month", pattern="^(today|week|month|custom)$"),
    provider: Optional[str] = None,
    api_key_id: Optional[str] = None,
    model: Optional[str] = None,
    repo_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    start, end = _parse_period(period, start_date, end_date)
    breakdown = await token_manager.get_cost_breakdown(
        db, current_user.id, start, end, provider, model, api_key_id, repo_id
    )
    records = await token_manager.get_usage_by_user(
        db, current_user.id, start, end, provider, model, api_key_id, repo_id, limit=10000
    )

    return UsageSummary(
        period=period,
        total_cost_usd=breakdown["total_cost_usd"],
        total_tokens=breakdown["total_tokens"],
        input_tokens=sum(r.input_tokens for r in records),
        output_tokens=sum(r.output_tokens for r in records),
        request_count=len(records),
        by_provider=breakdown["by_provider"],
        by_model=breakdown["by_model"],
        by_feature=breakdown["by_feature"],
    )


@router.get("/trend", response_model=List[DailyCost])
async def get_usage_trend(
    days: int = Query(30, ge=1, le=365),
    provider: Optional[str] = None,
    api_key_id: Optional[str] = None,
    model: Optional[str] = None,
    repo_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if start_date and end_date:
        delta = (end_date - start_date).days
        days = max(1, min(delta + 1, 365))
        now = end_date
    else:
        now = datetime.now(timezone.utc)
        start_date = (now - timedelta(days=days-1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = now

    daily_data = await token_manager.get_daily_trend(
        db, current_user.id, start_date, end_date, provider, model, api_key_id, repo_id
    )

    # Convert to dict for fast lookup
    daily_map = {d["date"]: d for d in daily_data}

    trend = []
    for i in range(days):
        day_start = (now - timedelta(days=days-1-i)).replace(hour=0, minute=0, second=0, microsecond=0)
        date_str = day_start.strftime("%Y-%m-%d")
        
        if date_str in daily_map:
            trend.append(DailyCost(
                date=date_str,
                cost_usd=round(daily_map[date_str]["cost_usd"], 6),
                tokens=daily_map[date_str]["tokens"]
            ))
        else:
            trend.append(DailyCost(
                date=date_str,
                cost_usd=0.0,
                tokens=0
            ))
            
    return list(reversed(trend))


@router.get("/breakdown")
async def get_usage_breakdown(
    period: str = Query("month", pattern="^(today|week|month|custom)$"),
    provider: Optional[str] = None,
    api_key_id: Optional[str] = None,
    model: Optional[str] = None,
    repo_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    start, end = _parse_period(period, start_date, end_date)
    return await token_manager.get_cost_breakdown(
        db, current_user.id, start, end, provider, model, api_key_id, repo_id
    )


@router.get("/records", response_model=List[UsageRecordRead])
async def get_usage_records(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    provider: Optional[str] = None,
    api_key_id: Optional[str] = None,
    model: Optional[str] = None,
    repo_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    records = await token_manager.get_usage_by_user(
        db, current_user.id, start=start_date, end=end_date, 
        provider=provider, model=model, 
        api_key_id=api_key_id, repo_id=repo_id, limit=limit, offset=offset
    )
    return records


# Budget endpoints
@router.get("/budgets", response_model=List[CostBudgetRead])
async def list_budgets(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await cost_estimator.get_budgets(db, current_user.id)


@router.post("/budgets", response_model=CostBudgetRead, status_code=201)
async def create_budget(
    data: CostBudgetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await cost_estimator.create_budget(db, current_user.id, data.model_dump())


@router.put("/budgets/{budget_id}", response_model=CostBudgetRead)
async def update_budget(
    budget_id: str,
    data: CostBudgetUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import uuid
    budget = await cost_estimator.update_budget(db, uuid.UUID(budget_id), data.model_dump(exclude_unset=True))
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    return budget


@router.delete("/budgets/{budget_id}", status_code=204)
async def delete_budget(
    budget_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import uuid
    deleted = await cost_estimator.delete_budget(db, uuid.UUID(budget_id))
    if not deleted:
        raise HTTPException(status_code=404, detail="Budget not found")
    return None

