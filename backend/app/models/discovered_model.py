import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import JSON_TYPE, Base


class DiscoveredModel(Base):
    __tablename__ = "discovered_models"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, index=True
    )
    provider_slug: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_free: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_metadata: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True)
    
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
