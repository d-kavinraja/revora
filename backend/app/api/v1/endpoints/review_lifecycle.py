"""Review lifecycle API endpoints.

Provides actions for retry, restart, rerun, and cancel of reviews.
Every action creates a NEW review record with a NEW execution context.
Existing reviews remain immutable.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError
from typing import Dict, Any, Optional
import uuid

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.review import Review
from app.services.review_lifecycle import (
    review_lifecycle_service,
    ReviewLifecycleConflict,
)

router = APIRouter()


def _get_client_info(request: Optional[Request]) -> tuple:
    if not request:
        return None, None
    return (
        request.client.host if request.client else None,
        request.headers.get("user-agent"),
    )


def _handle_error(e: Exception, action: str):
    if isinstance(e, ReviewLifecycleConflict):
        raise HTTPException(status_code=409, detail=str(e))
    if isinstance(e, ValueError):
        raise HTTPException(status_code=400, detail=str(e))
    if isinstance(e, ProgrammingError):
        msg = str(e)
        if "does not exist" in msg:
            raise HTTPException(
                status_code=500,
                detail="Database schema is out of date. Please run database migrations.",
            )
    raise HTTPException(status_code=500, detail=f"Failed to {action} review: {e}")


@router.post("/{review_id}/rerun", response_model=Dict[str, Any])
async def rerun_review(
    review_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    request: Request = None,
):
    try:
        rid = uuid.UUID(review_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid review ID")

    ip, ua = _get_client_info(request)

    try:
        result = await review_lifecycle_service.rerun_completed_review(
            db, rid, current_user.id, ip_address=ip, user_agent=ua
        )
        return result
    except Exception as e:
        _handle_error(e, "rerun")


@router.post("/{review_id}/retry", response_model=Dict[str, Any])
async def retry_review(
    review_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    request: Request = None,
):
    try:
        rid = uuid.UUID(review_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid review ID")

    ip, ua = _get_client_info(request)

    try:
        result = await review_lifecycle_service.retry_failed_review(
            db, rid, current_user.id, ip_address=ip, user_agent=ua
        )
        return result
    except Exception as e:
        _handle_error(e, "retry")


@router.post("/{review_id}/restart", response_model=Dict[str, Any])
async def restart_review(
    review_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    request: Request = None,
):
    try:
        rid = uuid.UUID(review_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid review ID")

    ip, ua = _get_client_info(request)

    try:
        result = await review_lifecycle_service.restart_stopped_review(
            db, rid, current_user.id, ip_address=ip, user_agent=ua
        )
        return result
    except Exception as e:
        _handle_error(e, "restart")


@router.get("/{review_id}/history", response_model=Dict[str, Any])
async def get_review_history(
    review_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        rid = uuid.UUID(review_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid review ID")

    review_result = await db.execute(select(Review).where(Review.id == rid))
    review = review_result.scalars().first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    history = await review_lifecycle_service.get_review_history(db, review.pr_id, review.id)

    return {
        "current_review_id": str(review.id),
        "current_status": review.status,
        "history": history["lifecycles"],
        "executions": history["executions"],
    }


@router.get("/{review_id}/timeline", response_model=Dict[str, Any])
async def get_review_timeline(
    review_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        rid = uuid.UUID(review_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid review ID")

    timeline = await review_lifecycle_service.get_review_timeline(db, rid)

    return {
        "review_id": str(rid),
        "timeline": timeline,
    }
