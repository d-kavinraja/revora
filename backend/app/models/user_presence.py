"""Per-tab presence for authenticated Revora users.

This table is deliberately **not** an authentication session store. The JWT
cookie remains authoritative for identity and revocation; these rows only record
that a browser tab is actively using the application so kLLM can decide whether
an approved model should be kept available.

No raw JWT ``jti`` or other reusable token identifier is stored: only a one-way
hash is kept alongside a client-generated per-tab identifier.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserPresence(Base):
    """A short-lived, heartbeat-refreshed browser presence record."""

    __tablename__ = "user_presence_sessions"
    __table_args__ = (
        Index(
            "uq_user_presence_user_client",
            "user_id",
            "client_session_id",
            unique=True,
        ),
        Index(
            "ix_user_presence_active_last_seen",
            "active",
            "last_seen_at",
        ),
        Index("ix_user_presence_expires_at", "expires_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    client_session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    token_jti_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
