"""AuditLog model for tracking repository and review lifecycle actions."""

import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from sqlalchemy import String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from app.db.base import Base, JSON_TYPE


class AuditLog(Base):
    __tablename__ = "audit_logs"

    actor_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False, default="user")  # user, system, github_app
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)  # e.g., repository.added, review.rerun
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)  # repository, review, installation, job
    entity_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON_TYPE, nullable=True, default=dict)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
