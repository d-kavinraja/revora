"""ReviewExecutionContext model for immutable execution context tracking."""

import uuid
from typing import Any

from sqlalchemy import Integer, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import JSON_TYPE, Base


class ReviewExecutionContext(Base):
    __tablename__ = "review_execution_contexts"

    review_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    repository_full_name: Mapped[str] = mapped_column(String(500), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    base_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    head_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    configuration_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_TYPE, nullable=True, default=dict
    )
