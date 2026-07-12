import json
import logging
from typing import Dict
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.review import Review

router = APIRouter()
logger = logging.getLogger(__name__)

# In-memory store for active review events (production would use Redis pub/sub)
_review_events: Dict[str, list] = {}


def store_events(review_id: str, events: list):
    _review_events[review_id] = events


def get_stored_events(review_id: str) -> list:
    return _review_events.get(review_id, [])


@router.get("/{review_id}/stream")
async def stream_review_events(
    review_id: str,
    current_user: User = Depends(get_current_user),
):
    """SSE endpoint that streams real-time pipeline events for a review."""

    import uuid
    try:
        rid = uuid.UUID(review_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid review ID")

    events = get_stored_events(review_id)

    async def event_generator():
        # Send historical events first
        for event in events:
            yield f"data: {json.dumps(event)}\n\n"

        # Then keep connection open for new events
        import asyncio
        sent_count = len(events)
        while True:
            await asyncio.sleep(1)
            current_events = get_stored_events(review_id)
            while sent_count < len(current_events):
                yield f"data: {json.dumps(current_events[sent_count])}\n\n"
                sent_count += 1

            # Check if review is complete
            if current_events and current_events[-1].get("stage") == "completed":
                break

            # Send heartbeat
            yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
