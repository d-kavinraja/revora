import asyncio
import signal
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal

_session_factory = AsyncSessionLocal

def set_session_factory(factory):
    global _session_factory
    _session_factory = factory
from app.models.api_key import ApiKey
from app.queue.operation_models import OperationJob
from app.services.validation_service import ValidationOutcome, validation_service

_worker_id = uuid.uuid4().hex[:8]
_operation_shutdown = False


def _handle_shutdown(signum, frame):
    _operation_shutdown = True


def _is_postgres(session: AsyncSession) -> bool:
    try:
        return session.get_bind().dialect.name == "postgresql"
    except Exception:
        return False


async def recover_operation_jobs() -> None:
    now = datetime.now(UTC)
    try:
        async with _session_factory() as session:
            stmt = select(OperationJob).where(
                OperationJob.status == "running",
            )
            result = await session.execute(stmt)
            jobs = list(result.scalars().all())
            for job in jobs:
                lease_expired = job.lease_expires_at is None or job.lease_expires_at < now
                if not lease_expired:
                    continue
                if job.attempt_count < settings.OPERATION_MAX_ATTEMPTS:
                    job.status = "queued"
                    job.available_at = now
                    job.worker_id = None
                    job.lease_expires_at = None
                    job.heartbeat_at = None
                else:
                    job.status = "failed"
                    job.finished_at = now
                    job.active_dedupe_key = None
                    if not job.error_text:
                        job.error_text = "Operation worker lease expired."
            cutoff = now - timedelta(days=settings.OPERATION_JOB_RETENTION_DAYS)
            await session.execute(
                delete(OperationJob).where(
                    OperationJob.status.in_(["completed", "failed", "cancelled"]),
                    OperationJob.active_dedupe_key.is_(None),
                    OperationJob.finished_at.is_not(None),
                    OperationJob.finished_at < cutoff,
                )
            )
            await session.commit()
    except Exception:
        pass


async def claim_next_operation_job(session: AsyncSession) -> OperationJob | None:
    now = datetime.now(UTC)
    stmt = (
        select(OperationJob)
        .where(
            OperationJob.status == "queued",
            OperationJob.available_at <= now,
        )
        .order_by(OperationJob.created_at.asc())
        .limit(1)
    )
    if _is_postgres(session):
        stmt = stmt.with_for_update(skip_locked=True)
    result = await session.execute(stmt)
    job = result.scalars().first()
    if job is None:
        return None
    job.status = "running"
    job.worker_id = _worker_id
    job.attempt_count += 1
    job.started_at = job.started_at or now
    job.lease_expires_at = now + timedelta(seconds=settings.OPERATION_LEASE_SECONDS)
    job.heartbeat_at = now
    await session.commit()
    await session.refresh(job)
    return job


async def _heartbeat(job_id: uuid.UUID, lost: asyncio.Event) -> None:
    while not lost.is_set():
        await asyncio.sleep(settings.OPERATION_HEARTBEAT_SECONDS)
        if lost.is_set():
            return
        try:
            async with _session_factory() as session:
                job = await session.get(OperationJob, job_id)
                if (
                    job is None
                    or job.worker_id != _worker_id
                    or job.status != "running"
                ):
                    lost.set()
                    return
                now = datetime.now(UTC)
                job.heartbeat_at = now
                job.lease_expires_at = now + timedelta(
                    seconds=settings.OPERATION_LEASE_SECONDS
                )
                await session.commit()
        except Exception:
            lost.set()
            return


def _owned(job: OperationJob | None) -> bool:
    return (
        job is not None
        and job.worker_id == _worker_id
        and job.status == "running"
    )


async def _finalize(
    session: AsyncSession, job: OperationJob, status: str, result: dict | None, error_text: str | None = None
) -> None:
    job.status = status
    job.result = result
    if result is not None:
        job.progress_current = result.get("progress_current", job.progress_current)
    job.finished_at = datetime.now(UTC)
    job.active_dedupe_key = None
    job.lease_expires_at = None
    job.heartbeat_at = None
    if error_text is not None:
        job.error_text = error_text[:300]
    session.add(job)
    await session.commit()


async def _requeue_or_fail(job_id: uuid.UUID, exc: Exception) -> None:
    try:
        async with _session_factory() as session:
            job = await session.get(OperationJob, job_id)
            if not _owned(job):
                return
            sanitized = str(exc)[:300]
            if job.attempt_count < settings.OPERATION_MAX_ATTEMPTS:
                job.status = "queued"
                job.available_at = datetime.now(UTC) + timedelta(
                    seconds=min(
                        60,
                        settings.OPERATION_RETRY_BACKOFF_SECONDS * max(1, job.attempt_count),
                    )
                )
                job.worker_id = None
                job.lease_expires_at = None
                job.heartbeat_at = None
                job.error_text = sanitized
            else:
                job.status = "failed"
                job.finished_at = datetime.now(UTC)
                job.active_dedupe_key = None
                job.error_text = sanitized
            session.add(job)
            await session.commit()
    except Exception:
        pass


async def _handle_api_key_test(job_id: uuid.UUID, lost: asyncio.Event) -> None:
    async with _session_factory() as session:
        job = await session.get(OperationJob, job_id)
        if job is not None:
            await session.refresh(job)
        if not _owned(job):
            return
        user_id = job.user_id
        payload = job.payload or {}
        key_id = uuid.UUID(payload["key_id"])

        result_items = {}
        if isinstance(job.result, dict):
            result_items = dict(job.result.get("items") or {})

        if str(key_id) in result_items:
            await _finalize(
                session,
                job,
                "completed",
                {
                    "summary": _summary_from_items(result_items, 1),
                    "items": result_items,
                    "progress_current": 1,
                },
            )
            return

        key = await session.get(ApiKey, key_id)
        if key is None or key.user_id != user_id:
            outcome = ValidationOutcome(
                status="failed",
                error_type="not_found",
                message="API key not found.",
                checked_at=datetime.now(UTC),
            )
        else:
            outcome = await validation_service.validate_key_record(
                session, key, force_refresh=True
            )

        if lost.is_set():
            raise RuntimeError("operation lease lost")

        item = _outcome_item(outcome)
        result_items[str(key_id)] = item
        result = {
            "summary": _summary_from_items(result_items, 1),
            "items": result_items,
            "progress_current": 1,
        }
        job.progress_current = 1
        job.progress_total = 1
        await _finalize(session, job, "completed", result)


async def _handle_validate_all(job_id: uuid.UUID, lost: asyncio.Event) -> None:
    async with _session_factory() as session:
        job = await session.get(OperationJob, job_id)
        if job is not None:
            await session.refresh(job)
        if not _owned(job):
            return
        user_id = job.user_id
        payload = job.payload or {}
        key_ids = list(payload.get("key_ids") or [])

    result_items = {}
    async with _session_factory() as session:
        job = await session.get(OperationJob, job_id)
        if isinstance(job.result, dict):
            result_items = dict(job.result.get("items") or {})

    for key_id in key_ids:
        if lost.is_set():
            raise RuntimeError("operation lease lost")
        if key_id in result_items and result_items[key_id].get("status") in {
            "success",
            "failed",
            "busy",
        }:
            continue

        outcome: ValidationOutcome
        async with _session_factory() as session:
            key = await session.get(ApiKey, uuid.UUID(key_id))
            if key is None or key.user_id != user_id:
                outcome = ValidationOutcome(
                    status="failed",
                    error_type="not_found",
                    message="API key not found.",
                    checked_at=datetime.now(UTC),
                )
            else:
                outcome = await validation_service.validate_key_record(
                    session, key, force_refresh=True
                )

        if lost.is_set():
            raise RuntimeError("operation lease lost")

        result_items[key_id] = _outcome_item(outcome)

        async with _session_factory() as session:
            job = await session.get(OperationJob, job_id)
            if not _owned(job):
                raise RuntimeError("operation lease lost")
            job.progress_current = len(result_items)
            job.progress_total = len(key_ids)
            job.result = {
                "summary": _summary_from_items(result_items, len(key_ids)),
                "items": result_items,
                "progress_current": len(result_items),
            }
            session.add(job)
            await session.commit()

    async with _session_factory() as session:
        job = await session.get(OperationJob, job_id)
        if job is not None:
            await session.refresh(job)
        if not _owned(job):
            return
        job.progress_current = len(result_items)
        job.progress_total = len(key_ids)
        await _finalize(
            session,
            job,
            "completed",
            {
                "summary": _summary_from_items(result_items, len(key_ids)),
                "items": result_items,
                "progress_current": len(result_items),
            },
        )


async def _handle_provider_health_check(job_id: uuid.UUID, lost: asyncio.Event) -> None:
    async with _session_factory() as session:
        job = await session.get(OperationJob, job_id)
        if job is not None:
            await session.refresh(job)
        if not _owned(job):
            return
        user_id = job.user_id
        payload = job.payload or {}
        provider = str(payload.get("provider") or "").lower()

    async with _session_factory() as session:
        outcome = await validation_service.check_provider(session, user_id, provider)

    if lost.is_set():
        raise RuntimeError("operation lease lost")

    async with _session_factory() as session:
        job = await session.get(OperationJob, job_id)
        if not _owned(job):
            return
        result = {
            "provider": provider,
            "status": outcome.status,
            "message": outcome.message,
            "error_type": outcome.error_type,
            "model": outcome.model,
            "latency_ms": outcome.latency_ms,
            "checked_at": outcome.checked_at.isoformat() if outcome.checked_at else None,
            "progress_current": 1,
        }
        job.progress_current = 1
        job.progress_total = 1
        await _finalize(session, job, "completed", result)


def _outcome_item(outcome: ValidationOutcome) -> dict:
    return {
        "status": outcome.status,
        "message": outcome.message,
        "error_type": outcome.error_type,
        "model": outcome.model,
        "latency_ms": outcome.latency_ms,
        "checked_at": outcome.checked_at.isoformat() if outcome.checked_at else None,
    }


def _summary_from_items(items: dict, total: int) -> dict:
    succeeded = sum(1 for item in items.values() if item.get("status") == "success")
    failed = sum(1 for item in items.values() if item.get("status") == "failed")
    busy = sum(1 for item in items.values() if item.get("status") == "busy")
    return {
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "busy": busy,
    }


async def run_operation_job(job_id: uuid.UUID) -> None:
    lost = asyncio.Event()
    heartbeat_task = asyncio.create_task(_heartbeat(job_id, lost))
    try:
        async with _session_factory() as session:
            job = await session.get(OperationJob, job_id)
            if job is not None:
                await session.refresh(job)
            if not _owned(job):
                return
            operation_type = job.operation_type
        if operation_type == "api_key_test":
            await _handle_api_key_test(job_id, lost)
        elif operation_type == "api_key_validate_all":
            await _handle_validate_all(job_id, lost)
        elif operation_type == "provider_health_check":
            await _handle_provider_health_check(job_id, lost)
        else:
            raise ValueError(f"Unknown operation type: {operation_type}")
    except Exception as exc:
        await _requeue_or_fail(job_id, exc)
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass


async def run_operation_worker(
    poll_interval: float | None = None,
    standalone: bool = False,
    max_jobs: int | None = None,
) -> None:
    if standalone:
        signal.signal(signal.SIGINT, _handle_shutdown)
        signal.signal(signal.SIGTERM, _handle_shutdown)

    await recover_operation_jobs()

    if poll_interval is None:
        poll_interval = settings.OPERATION_POLL_INTERVAL_SECONDS

    processed = 0
    while not _operation_shutdown and (max_jobs is None or processed < max_jobs):
        try:
            async with _session_factory() as session:
                job = await claim_next_operation_job(session)
            if job is None:
                await asyncio.sleep(poll_interval)
                continue
            await run_operation_job(job.id)
            processed += 1
        except Exception:
            await asyncio.sleep(poll_interval)


# Backwards-friendly alias for callers/tests that expect a single loop function.
run_worker = run_operation_worker
