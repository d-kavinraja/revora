"""Real-time event bus backed by database polling (no Redis required).

Producers (worker, lifecycle service, webhook handlers, background sync)
write to the database as usual — the database IS the bus. SSE endpoints
poll recently changed rows via an updated_at cursor and emit JSON events
to connected browsers.

This works across processes (API + workers share the DB) and deploys on
single-instance free tiers (e.g. Render Free) without extra services.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.github import Installation, PullRequest, Repository
from app.models.review import Review

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 1.0
HEARTBEAT_INTERVAL_SECONDS = 30.0
BATCH_LIMIT = 500


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


async def _poll_review_updates(
    cursor: datetime, user_id: str | None = None
) -> list[dict[str, Any]]:
    """Return review rows updated after `cursor`, oldest first, filtered by user_id if provided."""
    try:
        async with AsyncSessionLocal() as db:
            from app.models.execution import ReviewExecution

            stmt = select(Review).where(Review.updated_at > cursor)
            if user_id:
                stmt = (
                    stmt.join(PullRequest, PullRequest.id == Review.pr_id)
                    .join(Repository, Repository.id == PullRequest.repo_id)
                    .join(Installation, Installation.id == Repository.installation_id)
                    .where(Installation.user_id == user_id)
                )

            stmt = stmt.order_by(Review.updated_at.asc()).limit(BATCH_LIMIT)
            result = await db.execute(stmt)
            reviews = result.scalars().all()
            # Error detail lives on ReviewExecution (reviews has no
            # error_message column) — batch-fetch the latest execution per
            # review so the event payload shape is unchanged.
            error_map: dict[str, str | None] = {}
            if reviews:
                review_ids = [r.id for r in reviews]
                execs = (
                    (
                        await db.execute(
                            select(ReviewExecution)
                            .where(ReviewExecution.review_id.in_(review_ids))
                            .order_by(
                                ReviewExecution.review_id,
                                ReviewExecution.execution_number.desc(),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for ex in execs:
                    if ex.review_id not in error_map:
                        error_map[ex.review_id] = ex.error_message
            return [
                {
                    "type": "review.updated",
                    "review_id": str(r.id),
                    "pr_id": str(r.pr_id),
                    "status": r.status,
                    "error_message": error_map.get(r.id),
                    "updated_at": _iso(r.updated_at),
                }
                for r in reviews
            ]
    except Exception as e:
        logger.error(f"Event bus: failed to poll review updates: {e}", exc_info=True)
        return []


async def _poll_pr_state_updates(
    cursor: datetime, user_id: str | None = None
) -> list[dict[str, Any]]:
    """Return pull request rows updated after `cursor`, oldest first, filtered by user_id if provided."""
    try:
        async with AsyncSessionLocal() as db:
            stmt = select(PullRequest).where(PullRequest.updated_at > cursor)
            if user_id:
                stmt = (
                    stmt.join(Repository, Repository.id == PullRequest.repo_id)
                    .join(Installation, Installation.id == Repository.installation_id)
                    .where(Installation.user_id == user_id)
                )

            stmt = stmt.order_by(PullRequest.updated_at.asc()).limit(BATCH_LIMIT)
            result = await db.execute(stmt)
            return [
                {
                    "type": "pr.state",
                    "pr_id": str(p.id),
                    "pr_number": p.pr_number,
                    "repo_id": str(p.repo_id),
                    "status": p.status,
                    "updated_at": _iso(p.updated_at),
                }
                for p in result.scalars().all()
            ]
    except Exception as e:
        logger.error(f"Event bus: failed to poll PR state updates: {e}", exc_info=True)
        return []


async def event_generator(
    user_id: str,
    review_id: str | None = None,
    pr_id: str | None = None,
) -> AsyncIterator[str]:
    """SSE generator over DB-polled events.

    Args:
        review_id: When set, only events for this review are emitted.
        pr_id: When set, only PR-state events for this PR are emitted.
    """
    cursor = datetime.now(UTC)
    last_heartbeat = asyncio.get_event_loop().time()

    while True:
        events: list[dict[str, Any]] = []

        for ev in await _poll_review_updates(cursor, user_id=user_id):
            if review_id is None or ev["review_id"] == review_id:
                events.append(ev)

        for ev in await _poll_pr_state_updates(cursor, user_id=user_id):
            if review_id is None or pr_id is not None and ev["pr_id"] == pr_id:
                events.append(ev)

        for ev in events:
            yield f"data: {json.dumps(ev)}\n\n"

        cursor = datetime.now(UTC)

        if (
            asyncio.get_event_loop().time() - last_heartbeat
            >= HEARTBEAT_INTERVAL_SECONDS
        ):
            yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
            last_heartbeat = asyncio.get_event_loop().time()

        await asyncio.sleep(POLL_INTERVAL_SECONDS)
