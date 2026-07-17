import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Float, Integer, Boolean, Text, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LLMRequestLog(Base):
    """Complete LLM request trace for debugging and analytics."""

    __tablename__ = "llm_request_log"

    request_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Request
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    feature: Mapped[str] = mapped_column(String(50), nullable=False)
    messages_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA-256 fingerprint

    # Response
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # "success", "error", "fallback"
    response_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timing
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)

    # Tokens
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False)

    # Routing
    was_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    original_provider: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    api_key_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True
    )
    review_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("reviews.id", ondelete="SET NULL"), nullable=True
    )
