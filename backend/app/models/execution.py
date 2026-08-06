"""ReviewExecution model — one row per execution of a review lifecycle.

A review row is reused across reruns/retries/restarts and new-commit pushes;
each of those runs gets its own execution row for history tracking.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import JSON_TYPE, Base


class ReviewExecution(Base):
    __tablename__ = "review_executions"
    __table_args__ = (
        UniqueConstraint(
            "review_id",
            "execution_number",
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
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tokens: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_TYPE, nullable=True, default=dict
    )
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    
    # Review Metadata
    summary: Mapped[str | None] = mapped_column(String, nullable=True)
    stats: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_TYPE, nullable=True, default=dict
    )
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    
    # Execution Snapshot Context
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    configuration_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_TYPE, nullable=True, default=dict
    )
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    repository_full_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    base_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    head_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

