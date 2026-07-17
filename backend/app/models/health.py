import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Float, Integer, Text, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ApiKeyHealth(Base):
    """Health history for individual API keys."""

    __tablename__ = "api_key_health"

    key_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # "healthy", "degraded", "unhealthy"
    error_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProviderHealth(Base):
    """Provider-level health snapshots with circuit breaker state."""

    __tablename__ = "provider_health"

    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Status
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # "healthy", "degraded", "down"

    # Metrics
    avg_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    success_rate: Mapped[float] = mapped_column(Float, default=1.0)
    error_rate: Mapped[float] = mapped_column(Float, default=0.0)
    total_requests: Mapped[int] = mapped_column(Integer, default=0)
    failed_requests: Mapped[int] = mapped_column(Integer, default=0)

    # Circuit breaker
    circuit_state: Mapped[str] = mapped_column(String(20), default="closed")  # "closed", "open", "half_open"
    circuit_opened_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)

    # Errors
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_error_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class FailoverLog(Base):
    """Tracks every failover event for observability."""

    __tablename__ = "failover_log"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    feature: Mapped[str] = mapped_column(String(50), nullable=False)

    # From
    failed_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    failed_model: Mapped[str] = mapped_column(String(100), nullable=False)
    failure_reason: Mapped[str] = mapped_column(Text, nullable=False)

    # To
    fallback_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    fallback_model: Mapped[str] = mapped_column(String(100), nullable=False)

    # Context
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    total_latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
