"""SyncRun model — audit trail for automatic synchronization passes.

Every pass (startup / background / manual / webhook / recovery) records a
row with its reason, status, and counts so sync behavior is debuggable and
the UI can show "Last synchronized X ago".
"""

import uuid
from datetime import datetime
from typing import Optional, Dict, Any

from sqlalchemy import String, Integer, DateTime, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.db.base import Base, JSON_TYPE

# Sync reasons — recorded on every sync_runs row.
SYNC_REASON_STARTUP = "startup"
SYNC_REASON_BACKGROUND = "background"
SYNC_REASON_MANUAL = "manual"
SYNC_REASON_WEBHOOK = "webhook"
SYNC_REASON_RECOVERY = "recovery"

SYNC_REASONS = {
    SYNC_REASON_STARTUP,
    SYNC_REASON_BACKGROUND,
    SYNC_REASON_MANUAL,
    SYNC_REASON_WEBHOOK,
    SYNC_REASON_RECOVERY,
}

# Sync pass statuses.
SYNC_STATUS_RUNNING = "running"
SYNC_STATUS_SUCCESS = "success"
SYNC_STATUS_PARTIAL = "partial"
SYNC_STATUS_FAILED = "failed"


class SyncRun(Base):
    __tablename__ = "sync_runs"

    reason: Mapped[str] = mapped_column(String(20), nullable=False)
    triggered_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    repo_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repos_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repos_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repos_removed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repos_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prs_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prs_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_enqueued: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Per-repo failure map: {"full_name": "error message"} (partial failures).
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON_TYPE, nullable=True)
