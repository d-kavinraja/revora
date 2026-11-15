"""Durable processing for GitHub webhook deliveries (N4).

Acknowledgment contract: the HTTP endpoint returns 202 only after the
delivery row is committed. Processing then runs asynchronously; failures are
retried with bounded backoff and stale processing rows are recovered, so a
crash or transient error cannot silently drop an event.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.db.session import AsyncSessionLocal
from app.models.webhook_delivery import (
    COMPLETED,
    FAILED,
    PENDING,
    PROCESSING,
    WebhookDelivery,
)
from app.security.error_sanitizer import sanitize_error_message

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
RETRY_DELAYS = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(hours=1),
    timedelta(hours=6),
)
STALE_PROCESSING_AFTER = timedelta(minutes=15)
RETENTION = timedelta(days=30)
RECOVERY_INTERVAL_SECONDS = 60
RECOVERY_BATCH_SIZE = 50

# Indirection so tests can bind the service to their own engine.
_session_factory = AsyncSessionLocal


def _next_attempt_at(attempts: int, now: datetime | None = None) -> datetime:
    index = min(max(attempts - 1, 0), len(RETRY_DELAYS) - 1)
    return (now or datetime.now(UTC)) + RETRY_DELAYS[index]


async def record_delivery(
    event: str,
    action: str | None,
    payload: dict,
    delivery_id: str,
) -> tuple[WebhookDelivery | None, bool]:
    """Persist a delivery before acknowledging it.

    Returns (row, created). ``created`` is False for a duplicate delivery id
    (GitHub redelivery): the existing row is returned and must not be
    processed again unless it previously failed.
    """
    async with _session_factory() as db:
        row = WebhookDelivery(
            delivery_id=delivery_id,
            event=event,
            action=action,
            payload=payload,
            status=PENDING,
        )
        db.add(row)
        try:
            await db.commit()
            await db.refresh(row)
            return row, True
        except IntegrityError:
            await db.rollback()

    async with _session_factory() as db:
        result = await db.execute(
            select(WebhookDelivery).where(
                WebhookDelivery.delivery_id == delivery_id
            )
        )
        return result.scalars().first(), False


async def requeue_delivery(delivery_id: str) -> bool:
    """Allow a GitHub redelivery to retry a previously exhausted delivery."""
    async with _session_factory() as db:
        result = await db.execute(
            update(WebhookDelivery)
            .where(
                WebhookDelivery.delivery_id == delivery_id,
                WebhookDelivery.status == FAILED,
            )
            .values(
                status=PENDING,
                attempts=0,
                next_attempt_at=None,
                processing_started_at=None,
                last_error=None,
            )
        )
        await db.commit()
        return bool(result.rowcount)


async def _claim_delivery(delivery_id: str) -> tuple[str, dict | None]:
    """Atomically claim a delivery for processing.

    Returns (status, row_data). A row that is COMPLETED or actively being
    processed is not claimed again.
    """
    now = datetime.now(UTC)
    stale_before = now - STALE_PROCESSING_AFTER
    async with _session_factory() as db:
        claim = await db.execute(
            update(WebhookDelivery)
            .where(
                WebhookDelivery.delivery_id == delivery_id,
                or_(
                    WebhookDelivery.status == PENDING,
                    and_(
                        WebhookDelivery.status == PROCESSING,
                        or_(
                            WebhookDelivery.processing_started_at.is_(None),
                            WebhookDelivery.processing_started_at < stale_before,
                        ),
                    ),
                ),
            )
            .values(
                status=PROCESSING,
                attempts=WebhookDelivery.attempts + 1,
                processing_started_at=now,
                next_attempt_at=None,
            )
        )
        await db.commit()
        if claim.rowcount:
            claimed = await db.execute(
                select(WebhookDelivery).where(
                    WebhookDelivery.delivery_id == delivery_id
                )
            )
            row = claimed.scalars().first()
            if row is not None:
                return PROCESSING, {
                    "event": row.event,
                    "action": row.action,
                    "payload": row.payload,
                    "attempts": row.attempts,
                }

        result = await db.execute(
            select(WebhookDelivery.status).where(
                WebhookDelivery.delivery_id == delivery_id
            )
        )
        status = result.scalars().first()
        return (status or "missing"), None


async def _finish_delivery(
    delivery_id: str, status: str, error: object | None = None, attempts: int = 0
) -> str:
    now = datetime.now(UTC)
    async with _session_factory() as db:
        values: dict = {
            "status": status,
            "processing_started_at": None,
        }
        if status == COMPLETED:
            values["processed_at"] = now
            values["last_error"] = None
            values["next_attempt_at"] = None
        elif status == FAILED:
            values["processed_at"] = now
            values["next_attempt_at"] = None
            values["last_error"] = sanitize_error_message(error)
        else:
            values["next_attempt_at"] = _next_attempt_at(attempts)
            values["last_error"] = sanitize_error_message(error)
        await db.execute(
            update(WebhookDelivery)
            .where(WebhookDelivery.delivery_id == delivery_id)
            .values(**values)
        )
        await db.commit()
    return status


async def process_delivery(delivery_id: str) -> str:
    """Process one durable delivery. Safe to call concurrently/redelivered."""
    status, data = await _claim_delivery(delivery_id)
    if data is None:
        return status

    from app.github.webhooks import github_webhook_service

    try:
        await github_webhook_service.process_webhook(
            data["event"], data["action"] or "", data["payload"], delivery_id
        )
    except Exception as exc:
        attempts = int(data["attempts"] or 1)
        logger.exception(
            "Webhook delivery %s failed on attempt %s", delivery_id, attempts
        )
        if attempts >= MAX_ATTEMPTS:
            logger.error(
                "Webhook delivery %s exhausted %s attempts; giving up",
                delivery_id,
                MAX_ATTEMPTS,
            )
            return await _finish_delivery(delivery_id, FAILED, exc, attempts)
        return await _finish_delivery(delivery_id, PENDING, exc, attempts)

    return await _finish_delivery(delivery_id, COMPLETED)


async def recover_due_deliveries() -> dict[str, int]:
    """Recover stale processing rows and retry due pending deliveries."""
    now = datetime.now(UTC)
    recovered = 0
    async with _session_factory() as db:
        await db.execute(
            update(WebhookDelivery)
            .where(
                WebhookDelivery.status == PROCESSING,
                or_(
                    WebhookDelivery.processing_started_at.is_(None),
                    WebhookDelivery.processing_started_at
                    < now - STALE_PROCESSING_AFTER,
                ),
            )
            .values(status=PENDING, processing_started_at=None, next_attempt_at=None)
        )
        due = await db.execute(
            select(WebhookDelivery.delivery_id)
            .where(
                WebhookDelivery.status == PENDING,
                or_(
                    WebhookDelivery.next_attempt_at.is_(None),
                    WebhookDelivery.next_attempt_at <= now,
                ),
            )
            .order_by(WebhookDelivery.created_at)
            .limit(RECOVERY_BATCH_SIZE)
        )
        delivery_ids = list(due.scalars().all())
        await db.commit()

    for delivery_id in delivery_ids:
        try:
            await process_delivery(delivery_id)
            recovered += 1
        except Exception:
            logger.exception(
                "Recovery processing failed for webhook delivery %s", delivery_id
            )

    await _prune_payloads(now)
    return {"processed": recovered}


async def _prune_payloads(now: datetime) -> None:
    """Drop payload bodies after the retention window (PII minimization)."""
    cutoff = now - RETENTION
    try:
        async with _session_factory() as db:
            await db.execute(
                update(WebhookDelivery)
                .where(
                    WebhookDelivery.status.in_([COMPLETED, FAILED]),
                    WebhookDelivery.created_at < cutoff,
                    WebhookDelivery.payload != {},
                )
                .values(payload={})
            )
            await db.commit()
    except Exception:
        logger.warning("Webhook delivery payload pruning failed", exc_info=True)


async def webhook_delivery_loop() -> None:
    """Periodic retry/recovery loop (started from the app lifespan)."""
    while True:
        try:
            await asyncio.sleep(RECOVERY_INTERVAL_SECONDS)
            result = await recover_due_deliveries()
            if result["processed"]:
                logger.info(
                    "Recovered %s pending webhook deliveries", result["processed"]
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Webhook delivery recovery loop failed")
