import uuid
from typing import Optional, Dict, List
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.health import ProviderHealth, FailoverLog

CIRCUIT_BREAKER_THRESHOLD = 5  # failures before opening
CIRCUIT_BREAKER_TIMEOUT = 300  # seconds before half_open


class HealthMonitor:
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    async def get_or_create(self, db: AsyncSession, provider: str) -> ProviderHealth:
        result = await db.execute(
            select(ProviderHealth).where(ProviderHealth.provider == provider)
        )
        health = result.scalars().first()
        if not health:
            health = ProviderHealth(
                provider=provider,
                status="healthy",
                circuit_state=self.CLOSED,
            )
            db.add(health)
            await db.commit()
            await db.refresh(health)
        return health

    async def record_success(self, db: AsyncSession, provider: str, latency_ms: float) -> None:
        health = await self.get_or_create(db, provider)
        health.total_requests += 1
        health.avg_latency_ms = (
            (health.avg_latency_ms * (health.total_requests - 1) + latency_ms)
            / health.total_requests
        )
        health.success_rate = min(1.0, health.success_rate + 0.05)
        health.error_rate = max(0.0, health.error_rate - 0.02)
        health.consecutive_failures = 0
        health.status = "healthy"

        # Proper state transitions
        if health.circuit_state == self.OPEN:
            # Open -> Half Open (testing recovery)
            health.circuit_state = self.HALF_OPEN
        elif health.circuit_state == self.HALF_OPEN:
            # Half Open -> Closed (recovery confirmed)
            health.circuit_state = self.CLOSED
            health.circuit_opened_at = None
        # Closed -> Closed (no change needed)

        db.add(health)
        await db.commit()

    async def record_failure(self, db: AsyncSession, provider: str, error_type: str, error_msg: str) -> None:
        health = await self.get_or_create(db, provider)
        health.total_requests += 1
        health.failed_requests += 1
        health.success_rate = max(0.0, health.success_rate - 0.1)
        health.error_rate = min(1.0, health.error_rate + 0.1)
        health.consecutive_failures += 1
        health.last_error = error_msg
        health.last_error_at = datetime.now(timezone.utc)

        # Proper state transitions
        if health.circuit_state == self.HALF_OPEN:
            # Half Open -> Open (recovery failed)
            health.circuit_state = self.OPEN
            health.circuit_opened_at = datetime.now(timezone.utc)
            health.status = "down"
        elif health.consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD:
            # Closed -> Open (too many failures)
            health.circuit_state = self.OPEN
            health.circuit_opened_at = datetime.now(timezone.utc)
            health.status = "down"
        elif health.consecutive_failures >= 2:
            health.status = "degraded"

        db.add(health)
        await db.commit()

    async def should_allow_request(self, db: AsyncSession, provider: str) -> bool:
        health = await self.get_or_create(db, provider)

        if health.circuit_state == self.CLOSED:
            return True

        if health.circuit_state == self.OPEN:
            # Check if timeout has passed
            if health.circuit_opened_at:
                elapsed = (datetime.now(timezone.utc) - health.circuit_opened_at).total_seconds()
                if elapsed > CIRCUIT_BREAKER_TIMEOUT:
                    # Transition to half_open to test recovery
                    health.circuit_state = self.HALF_OPEN
                    db.add(health)
                    await db.commit()
                    return True
            return False

        if health.circuit_state == self.HALF_OPEN:
            # Allow one request to test recovery
            return True

        return True

    async def get_all_health(self, db: AsyncSession) -> List[ProviderHealth]:
        result = await db.execute(select(ProviderHealth))
        return list(result.scalars().all())

    async def get_health(self, db: AsyncSession, provider: str) -> Optional[ProviderHealth]:
        return await self.get_or_create(db, provider)

    async def get_circuit_breakers(self, db: AsyncSession) -> Dict[str, str]:
        healths = await self.get_all_health(db)
        return {h.provider: h.circuit_state for h in healths}

    async def log_failover(
        self, db: AsyncSession, user_id: uuid.UUID, feature: str,
        failed_provider: str, failed_model: str, failure_reason: str,
        fallback_provider: str, fallback_model: str,
        attempt_number: int, total_latency_ms: float,
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

    async def get_recent_failovers(self, db: AsyncSession, user_id: uuid.UUID, limit: int = 20) -> List[FailoverLog]:
        result = await db.execute(
            select(FailoverLog)
            .where(FailoverLog.user_id == user_id)
            .order_by(FailoverLog.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


health_monitor = HealthMonitor()
