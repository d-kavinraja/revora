from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.usage_tracker import usage_tracker

router = APIRouter()


@router.get("/requests")
async def list_requests(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_key_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get paginated request log."""
    requests = await usage_tracker.get_user_requests(
        db, current_user.id, limit, offset, provider, model, api_key_id, repo_id, start_date, end_date
    )
    return [r.__dict__ for r in requests]


@router.get("/errors")
async def get_errors(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_key_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get error summary."""
    return await usage_tracker.get_error_summary(
        db, current_user.id, provider, model, api_key_id, repo_id, start_date, end_date
    )


@router.get("/latency")
async def get_latency(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_key_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get latency statistics."""
    return await usage_tracker.get_latency_stats(
        db, current_user.id, provider, model, api_key_id, repo_id, start_date, end_date
    )


@router.get("/features")
async def get_feature_usage(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_key_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get feature usage breakdown."""
    return await usage_tracker.get_feature_usage(
        db, current_user.id, provider, model, api_key_id, repo_id, start_date, end_date
    )


@router.get("/providers")
async def get_provider_comparison(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_key_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get provider performance comparison."""
    return await usage_tracker.get_provider_comparison(
        db, current_user.id, provider, model, api_key_id, repo_id, start_date, end_date
    )
