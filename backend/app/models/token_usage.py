import uuid
from typing import Optional
from sqlalchemy import String, Float, Integer, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LlmTokenUsage(Base):
    """Per-request token consumption. Source of truth for usage tracking."""

    __tablename__ = "llm_token_usage"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    api_key_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True
    )

    # Token counts
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False)

    # Cost (computed at write time)
    input_cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    output_cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    total_cost_usd: Mapped[float] = mapped_column(Float, nullable=False)

    # Context
    feature: Mapped[str] = mapped_column(String(50), nullable=False)  # "code_review", etc.
    review_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("reviews.id", ondelete="SET NULL"), nullable=True
    )
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Metadata
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)


class CostBudget(Base):
    """Budget constraints for cost control."""

    __tablename__ = "cost_budgets"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    budget_type: Mapped[str] = mapped_column(String(20), nullable=False)  # "daily", "monthly"
    limit_usd: Mapped[float] = mapped_column(Float, nullable=False)
    spent_usd: Mapped[float] = mapped_column(Float, default=0.0)

    # Scope (NULL = all)
    provider: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    feature: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # State
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    reset_at: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)  # ISO datetime
