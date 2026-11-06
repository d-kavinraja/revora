import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.health import FailoverLog, ProviderHealth

CIRCUIT_BREAKER_THRESHOLD = 5
CIRCUIT_BREAKER_TIMEOUT = 300


class HealthMonitor:
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    async def get_or_create(
        self, db: AsyncSession, provider: str, user_id: uuid.UUID | None = None
    ) -> ProviderHealth:
        if user_id is None:
            stmt = select(ProviderHealth).where(
                ProviderHealth.user_id.is_(None),
                ProviderHealth.provider == provider,
            )
        else:
            stmt = select(ProviderHealth).where(
                ProviderHealth.user_id == user_id,
                ProviderHealth.provider == provider,
            )
        result = await db.execute(stmt)
        health = result.scalars().first()
        if not health:
            health = ProviderHealth(
                user_id=user_id,
                provider=provider,
                status="healthy",
                circuit_state=self.CLOSED,
            )
            db.add(health)
            await db.commit()
            await db.refresh(health)
        return health

    async def record_success(
        self,
        db: AsyncSession,
        provider: str,
        latency_ms: float,
        model_name: str | None = None,
        user_id: uuid.UUID | None = None,
    ) -> None:
        health = await self.get_or_create(db, provider, user_id=user_id)
        health.total_requests += 1
        health.avg_latency_ms = (
            health.avg_latency_ms * (health.total_requests - 1) + latency_ms
        ) / health.total_requests
        health.failed_requests = min(health.failed_requests, health.total_requests)
        health.success_rate = (
            (health.total_requests - health.failed_requests) / health.total_requests
            if health.total_requests
            else 1.0
        )
        health.error_rate = (
            health.failed_requests / health.total_requests
            if health.total_requests
            else 0.0
        )
        health.consecutive_failures = 0
        health.status = "healthy"
        health.last_error = None
        health.last_error_at = None
        health.last_checked_at = datetime.now(UTC)
        health.last_latency_ms = latency_ms
        health.last_model = model_name

        if health.circuit_state == self.OPEN:
            health.circuit_state = self.HALF_OPEN
        elif health.circuit_state == self.HALF_OPEN:
            health.circuit_state = self.CLOSED
            health.circuit_opened_at = None

        db.add(health)
        await db.commit()

    async def record_failure(
        self,
        db: AsyncSession,
        provider: str,
        error_type: str,
        error_msg: str,
        latency_ms: float | None = None,
        model_name: str | None = None,
        user_id: uuid.UUID | None = None,
        auth_failure: bool = False,
    ) -> None:
        health = await self.get_or_create(db, provider, user_id=user_id)
        health.total_requests += 1
        health.failed_requests += 1
        health.avg_latency_ms = (
            (health.avg_latency_ms * (health.total_requests - 1) + (latency_ms or 0.0))
            / health.total_requests
            if health.total_requests
            else 0.0
        )
        health.success_rate = (
            (health.total_requests - health.failed_requests) / health.total_requests
            if health.total_requests
            else 0.0
        )
        health.error_rate = (
            health.failed_requests / health.total_requests
            if health.total_requests
            else 1.0
        )
        health.last_error = error_msg[:300] if error_msg else None
        health.last_error_at = datetime.now(UTC)
        health.last_checked_at = datetime.now(UTC)
        health.last_latency_ms = latency_ms
        health.last_model = model_name

        if auth_failure:
            health.status = "degraded"
        else:
            health.consecutive_failures += 1
            if health.circuit_state == self.HALF_OPEN:
                health.circuit_state = self.OPEN
                health.circuit_opened_at = datetime.now(UTC)
                health.status = "down"
            elif health.consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD:
                health.circuit_state = self.OPEN
                health.circuit_opened_at = datetime.now(UTC)
                health.status = "down"
            elif health.consecutive_failures >= 2:
                health.status = "degraded"

        db.add(health)
        await db.commit()

    async def should_allow_request(
        self, db: AsyncSession, provider: str, user_id: uuid.UUID | None = None
    ) -> bool:
        health = await self.get_or_create(db, provider, user_id=user_id)

        if health.circuit_state == self.CLOSED:
            return True

        if health.circuit_state == self.OPEN:
            if health.circuit_opened_at:
                elapsed = (datetime.now(UTC) - health.circuit_opened_at).total_seconds()
                if elapsed > CIRCUIT_BREAKER_TIMEOUT:
                    health.circuit_state = self.HALF_OPEN
                    db.add(health)
                    await db.commit()
                    return True
            return False

        if health.circuit_state == self.HALF_OPEN:
            return True

        return True

    async def get_all_health(
        self, db: AsyncSession, user_id: uuid.UUID | None = None
    ) -> list[ProviderHealth]:
        if user_id is None:
            stmt = select(ProviderHealth).where(ProviderHealth.user_id.is_(None))
        else:
            stmt = select(ProviderHealth).where(ProviderHealth.user_id == user_id)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_health(
        self, db: AsyncSession, provider: str, user_id: uuid.UUID | None = None
    ) -> ProviderHealth | None:
        return await self.get_or_create(db, provider, user_id=user_id)

    async def get_circuit_breakers(
        self, db: AsyncSession, user_id: uuid.UUID | None = None
    ) -> dict[str, str]:
        healths = await self.get_all_health(db, user_id=user_id)
        return {h.provider: h.circuit_state for h in healths}

    async def log_failover(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        feature: str,
        failed_provider: str,
        failed_model: str,
        failure_reason: str,
        fallback_provider: str,
        fallback_model: str,
        attempt_number: int,
        total_latency_ms: float,
    ) -> FailoverLog:
        log = FailoverLog(
            user_id=user_id,
            feature=feature,
            failed_provider=failed_provider,
            failed_model=failed_model,
            failure_reason=failure_reason,
            fallback_provider=fallback_provider,
            fallback_model=fallback_model,
            attempt_number=attempt_number,
            total_latency_ms=total_latency_ms,
        )
        db.add(log)
        await db.commit()
        await db.refresh(log)
        return log

    async def get_recent_failovers(
        self, db: AsyncSession, user_id: uuid.UUID, limit: int = 20
    ) -> list[FailoverLog]:
        result = await db.execute(
            select(FailoverLog)
            .where(FailoverLog.user_id == user_id)
            .order_by(FailoverLog.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


health_monitor = HealthMonitor()
