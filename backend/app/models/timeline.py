"""ReviewTimeline model for tracking review execution stages."""

import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from sqlalchemy import String, Float, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from app.db.base import Base, JSON_TYPE


class ReviewTimeline(Base):
    __tablename__ = "review_timelines"

    review_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="waiting")  # waiting, running, completed, failed, skipped
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    metrics: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON_TYPE, nullable=True, default=dict)
