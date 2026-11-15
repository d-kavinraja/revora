"""Regression tests for the durable webhook delivery outbox (N4).

A 202 Accepted is only returned once the delivery row is committed;
failures retry with bounded backoff; stale rows are recovered; an explicit
GitHub redelivery of an exhausted delivery gets a fresh attempt budget.
"""
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from unittest.mock import AsyncMock

import app.models  # noqa: F401  (register tables)
import app.services.webhook_delivery_service as wds
from app.core.config import settings
from app.db.base import Base
from app.github.webhooks import github_webhook_service
from app.main import app
from app.middleware.rate_limit import limiter
from app.models.webhook_delivery import (
    COMPLETED,
    FAILED,
    PENDING,
    PROCESSING,
    WebhookDelivery,
)


@pytest.fixture(autouse=True)
def _reset_limiter():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
async def webhook_env(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    monkeypatch.setattr(wds, "_session_factory", factory)
    yield factory
    await engine.dispose()


def _delivery_id() -> str:
    return f"delivery-{uuid.uuid4()}"


async def _get_row(factory, delivery_id: str) -> WebhookDelivery | None:
    async with factory() as db:
        from sqlalchemy import select

        result = await db.execute(
            select(WebhookDelivery).where(WebhookDelivery.delivery_id == delivery_id)
        )
        return result.scalars().first()


async def _seed_row(factory, delivery_id: str, **values) -> None:
    row_values = {
        "delivery_id": delivery_id,
        "event": "pull_request",
        "action": "opened",
        "payload": {"action": "opened"},
        "status": PENDING,
    }
    row_values.update(values)
    async with factory() as db:
        row = WebhookDelivery(**row_values)
        db.add(row)
        await db.commit()


async def test_record_delivery_persists_before_acknowledge(webhook_env):
    delivery_id = _delivery_id()
    row, created = await wds.record_delivery(
        "ping", None, {"zen": "ok"}, delivery_id
    )
    assert created is True
    assert row.status == PENDING
    assert row.attempts == 0

    duplicate, created = await wds.record_delivery(
        "ping", None, {"zen": "ok"}, delivery_id
    )
    assert created is False
    assert duplicate.id == row.id


async def test_process_delivery_marks_completed_on_success(webhook_env, monkeypatch):
    handler = AsyncMock(return_value=None)
    monkeypatch.setattr(github_webhook_service, "process_webhook", handler)

    delivery_id = _delivery_id()
    await wds.record_delivery("ping", None, {"zen": "ok"}, delivery_id)
    result = await wds.process_delivery(delivery_id)

    assert result == COMPLETED
    handler.assert_awaited_once()
    row = await _get_row(webhook_env, delivery_id)
    assert row.status == COMPLETED
    assert row.processed_at is not None
    assert row.last_error is None


async def test_process_delivery_failure_schedules_retry_and_sanitizes_error(
    webhook_env, monkeypatch
):
    async def failing_handler(*args, **kwargs):
        raise RuntimeError("token: abc123secret failed for https://x.example.com/y")

    monkeypatch.setattr(github_webhook_service, "process_webhook", failing_handler)

    delivery_id = _delivery_id()
    await wds.record_delivery("ping", None, {}, delivery_id)
    result = await wds.process_delivery(delivery_id)

    assert result == PENDING
    row = await _get_row(webhook_env, delivery_id)
    assert row.attempts == 1
    assert row.last_error is not None
    assert "abc123secret" not in row.last_error
    assert "https://x.example.com/y" not in row.last_error
    assert "[redacted]" in row.last_error
    assert row.next_attempt_at is not None
    # SQLite returns naive datetimes; normalize before comparing.
    next_attempt = row.next_attempt_at
    if next_attempt.tzinfo is None:
        next_attempt = next_attempt.replace(tzinfo=UTC)
    assert next_attempt > datetime.now(UTC)


async def test_process_delivery_exhaustion_marks_failed(webhook_env, monkeypatch):
    async def failing_handler(*args, **kwargs):
        raise RuntimeError("permanent failure")

    monkeypatch.setattr(github_webhook_service, "process_webhook", failing_handler)

    delivery_id = _delivery_id()
    await _seed_row(webhook_env, delivery_id, attempts=4)
    result = await wds.process_delivery(delivery_id)

    assert result == FAILED
    row = await _get_row(webhook_env, delivery_id)
    assert row.status == FAILED
    assert row.attempts == 5
    assert row.processed_at is not None


async def test_stale_processing_delivery_is_recovered(webhook_env, monkeypatch):
    handler = AsyncMock(return_value=None)
    monkeypatch.setattr(github_webhook_service, "process_webhook", handler)

    delivery_id = _delivery_id()
    stale = datetime.now(UTC) - timedelta(minutes=20)
    await _seed_row(
        webhook_env,
        delivery_id,
        status=PROCESSING,
        attempts=1,
        processing_started_at=stale,
    )

    result = await wds.recover_due_deliveries()

    assert result["processed"] >= 1
    handler.assert_awaited_once()
    row = await _get_row(webhook_env, delivery_id)
    assert row.status == COMPLETED


async def test_requeue_delivery_gives_failed_delivery_fresh_budget(webhook_env):
    delivery_id = _delivery_id()
    await _seed_row(
        webhook_env,
        delivery_id,
        status=FAILED,
        attempts=5,
        last_error="exhausted",
    )

    assert await wds.requeue_delivery(delivery_id) is True
    row = await _get_row(webhook_env, delivery_id)
    assert row.status == PENDING
    assert row.attempts == 0
    assert row.last_error is None
    assert row.next_attempt_at is None

    # No longer FAILED, so a second requeue is a no-op.
    assert await wds.requeue_delivery(delivery_id) is False


# ---------------------------------------------------------------------------
# Endpoint contract: 202 only after durable persistence.
# ---------------------------------------------------------------------------

def _signed_headers(body: bytes, delivery_id: str) -> dict[str, str]:
    signature = (
        "sha256="
        + hmac.new(
            settings.GITHUB_WEBHOOK_SECRET.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
    )
    return {
        "X-GitHub-Event": "ping",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": signature,
        "Content-Type": "application/json",
    }


async def test_valid_webhook_returns_202_after_persist(
    webhook_env, monkeypatch
):
    monkeypatch.setattr(
        "app.api.v1.endpoints.webhooks.process_delivery", AsyncMock()
    )
    payload = {"zen": "Keep it logically awesome."}
    delivery_id = _delivery_id()
    body = json.dumps(payload).encode()

    client = TestClient(app)
    response = client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers=_signed_headers(body, delivery_id),
    )

    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
    row = await _get_row(webhook_env, delivery_id)
    assert row is not None
    assert row.status == PENDING
    assert row.payload["zen"] == payload["zen"]


async def test_duplicate_completed_delivery_returns_duplicate_ack(
    webhook_env, monkeypatch
):
    process_mock = AsyncMock()
    monkeypatch.setattr(
        "app.api.v1.endpoints.webhooks.process_delivery", process_mock
    )
    delivery_id = _delivery_id()
    await _seed_row(
        webhook_env,
        delivery_id,
        status=COMPLETED,
        attempts=1,
        processed_at=datetime.now(UTC),
    )

    payload = {"zen": "already done"}
    body = json.dumps(payload).encode()
    client = TestClient(app)
    response = client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers=_signed_headers(body, delivery_id),
    )

    assert response.status_code == 202
    assert response.json()["status"] == "duplicate"
    process_mock.assert_not_awaited()


async def test_redelivery_of_failed_delivery_is_requeued(
    webhook_env, monkeypatch
):
    process_mock = AsyncMock()
    monkeypatch.setattr(
        "app.api.v1.endpoints.webhooks.process_delivery", process_mock
    )
    delivery_id = _delivery_id()
    await _seed_row(
        webhook_env,
        delivery_id,
        status=FAILED,
        attempts=5,
        last_error="exhausted",
    )

    payload = {"zen": "try again"}
    body = json.dumps(payload).encode()
    client = TestClient(app)
    response = client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers=_signed_headers(body, delivery_id),
    )

    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
    row = await _get_row(webhook_env, delivery_id)
    assert row.status == PENDING
    assert row.attempts == 0
    # Background tasks run within TestClient: the patched processor is called
    # with the delivery id.
    process_mock.assert_awaited_once_with(delivery_id)


async def test_persist_failure_returns_503_not_202(webhook_env, monkeypatch):
    async def broken_record(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        "app.api.v1.endpoints.webhooks.record_delivery", broken_record
    )

    payload = {"zen": "boom"}
    delivery_id = _delivery_id()
    body = json.dumps(payload).encode()
    client = TestClient(app)
    response = client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers=_signed_headers(body, delivery_id),
    )

    assert response.status_code == 503
    assert "could not be persisted" in response.json()["detail"]
