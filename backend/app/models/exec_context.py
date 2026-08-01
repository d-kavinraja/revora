"""ReviewExecutionContext model for immutable execution context tracking."""

import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from sqlalchemy import String, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from app.db.base import Base, JSON_TYPE


class ReviewExecutionContext(Base):
    __tablename__ = "review_execution_contexts"

    review_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    repository_full_name: Mapped[str] = mapped_column(String(500), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    api_key_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    base_branch: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    head_branch: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    pr_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    configuration_snapshot: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON_TYPE, nullable=True, default=dict)
