"""ReviewExecution model — one row per execution of a review lifecycle.

A review row is reused across reruns/retries/restarts and new-commit pushes;
each of those runs gets its own execution row for history tracking.
"""

import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy import String, Integer, BigInteger, DateTime, UniqueConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from app.db.base import Base, JSON_TYPE


class ReviewExecution(Base):
    __tablename__ = "review_executions"
    __table_args__ = (
        UniqueConstraint(
            "review_id", "execution_number",
            name="uq_review_executions_review_id_execution_number",
        ),
    )

    review_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("reviews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    execution_number: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, default="webhook")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    provider: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tokens: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON_TYPE, nullable=True, default=dict)
    commit_sha: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
