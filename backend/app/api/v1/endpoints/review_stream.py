"""SSE endpoints for real-time review and PR state updates.

The list stream (GET /reviews/stream) emits review + PR state changes for
every review the connected user can see; the detail stream
(GET /reviews/{review_id}/stream) is scoped to one review and its PR.
Both are backed by database polling (see app.services.event_bus) so they
work across the API/worker processes without Redis.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.core.deps import get_current_user
from app.db.session import AsyncSessionLocal
from app.models.user import User
from app.models.review import Review
from app.services.event_bus import event_generator

router = APIRouter()
logger = logging.getLogger(__name__)

_STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@router.get("/stream")
async def stream_all_review_events(
    current_user: User = Depends(get_current_user),
):
    """SSE stream of review and PR state updates for the reviews list."""

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=_STREAM_HEADERS,
    )


@router.get("/{review_id}/stream")
async def stream_review_events(
    review_id: str,
    current_user: User = Depends(get_current_user),
):
    """SSE stream scoped to a single review and its pull request."""

    try:
        rid = uuid.UUID(review_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid review ID")

    pr_id = None
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Review.pr_id).where(Review.id == rid)
            )
            pr_id = result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Failed to resolve PR for review {review_id}: {e}", exc_info=True)

    return StreamingResponse(
        event_generator(
            review_id=str(rid),
            pr_id=str(pr_id) if pr_id else None,
        ),
        media_type="text/event-stream",
        headers=_STREAM_HEADERS,
    )
