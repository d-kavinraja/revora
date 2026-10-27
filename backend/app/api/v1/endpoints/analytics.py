from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.deps_flags import FeatureDisabledError, feature_message
from app.db.session import get_db
from app.models.user import User
from app.services.platform_settings import platform_settings_service
from app.services.usage_tracker import usage_tracker

router = APIRouter()


async def require_usage_enabled(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Env remains master (§11.1): its contract/message is unchanged.
    if not settings.USAGE_ANALYTICS_ENABLED:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "disabled",
                "message": "Usage analytics are temporarily disabled while we redesign model-level pricing. "
                "No data has been lost; this feature will be re-enabled in a future release.",
            },
        )
    if getattr(current_user, "role", "user") == "admin":
        return
    flag = await platform_settings_service.get_flag("analytics", db)
    status = flag.get("status") or "enabled"
    if status != "enabled":
        raise FeatureDisabledError(
            "analytics", feature_message("analytics", status, flag.get("message"))
        )


@router.get("/requests")
async def list_requests(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    provider: str | None = None,
    model: str | None = None,
    api_key_id: str | None = None,
    repo_id: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_usage_enabled),
):
    """Get paginated request log."""
    requests = await usage_tracker.get_user_requests(
        db,
        current_user.id,
        limit,
        offset,
        provider,
        model,
        api_key_id,
        repo_id,
        start_date,
        end_date,
    )
    return [r.__dict__ for r in requests]


@router.get("/errors")
async def get_errors(
    provider: str | None = None,
    model: str | None = None,
    api_key_id: str | None = None,
    repo_id: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_usage_enabled),
):
    """Get error summary."""
    return await usage_tracker.get_error_summary(
        db, current_user.id, provider, model, api_key_id, repo_id, start_date, end_date
    )


@router.get("/latency")
async def get_latency(
    provider: str | None = None,
    model: str | None = None,
    api_key_id: str | None = None,
    repo_id: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_usage_enabled),
):
    """Get latency statistics."""
    return await usage_tracker.get_latency_stats(
        db, current_user.id, provider, model, api_key_id, repo_id, start_date, end_date
    )


@router.get("/features")
async def get_feature_usage(
    provider: str | None = None,
    model: str | None = None,
    api_key_id: str | None = None,
    repo_id: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_usage_enabled),
):
    """Get feature usage breakdown."""
    return await usage_tracker.get_feature_usage(
        db, current_user.id, provider, model, api_key_id, repo_id, start_date, end_date
    )


@router.get("/providers")
async def get_provider_comparison(
    provider: str | None = None,
    model: str | None = None,
    api_key_id: str | None = None,
    repo_id: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_usage_enabled),
):
    """Get provider performance comparison."""
    return await usage_tracker.get_provider_comparison(
        db, current_user.id, provider, model, api_key_id, repo_id, start_date, end_date
    )
