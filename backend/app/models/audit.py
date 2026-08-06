"""AuditLog model for tracking repository and review lifecycle actions."""

from typing import Any

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import JSON_TYPE, Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    actor_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    actor_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="user"
    )  # user, system, github_app
    action: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )  # e.g., repository.added, review.rerun
    entity_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # repository, review, installation, job
    entity_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_TYPE, nullable=True, default=dict
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
