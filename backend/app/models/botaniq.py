"""BotaniQ inference run model (inference-only, no training)."""

import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BotaniqInferenceRun(Base):
    """Persisted BotaniQ medicinal plant inference execution."""

    __tablename__ = "botaniq_inference_runs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    image_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    image_size_bytes: Mapped[int | None] = mapped_column(nullable=True)
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="upload"
    )  # upload | test | url
    test_image_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prediction: Mapped[str | None] = mapped_column(Text, nullable=True)
    predicted_class: Mapped[str | None] = mapped_column(String(255), nullable=True)
    plant_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    plant_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)  # 0–100
    top_5_predictions: Mapped[list[Any] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    inference_time_ms: Mapped[int | None] = mapped_column(nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
