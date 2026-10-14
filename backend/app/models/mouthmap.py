"""MouthMap inference-only models (no training)."""

import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MouthmapInferenceRun(Base):
    """Persisted MouthMap inference execution (real runs only, no mocks)."""

    __tablename__ = "mouthmap_inference_runs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    video_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    video_size_bytes: Mapped[int | None] = mapped_column(nullable=True)
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="upload"
    )  # test | upload | record
    test_video_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prediction: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_match: Mapped[bool | None] = mapped_column(nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    inference_time_ms: Mapped[int | None] = mapped_column(nullable=True)
    frames_processed: Mapped[int | None] = mapped_column(nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
