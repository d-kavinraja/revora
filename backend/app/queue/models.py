"""ReviewJob model for the Postgres-native job queue."""

import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB, ENUM
from app.db.base import Base


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReviewJob(Base):
    __tablename__ = "review_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repo_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id"), nullable=True)
    pr_number = Column(Integer, nullable=False)
    head_sha = Column(String(40), nullable=False)
    base_sha = Column(String(40), nullable=True)
    delivery_id = Column(String(100), nullable=False, index=True)
    status = Column(
        ENUM(JobStatus, name="job_status", create_type=False),
        nullable=False,
        default=JobStatus.QUEUED,
        index=True,
    )
    payload = Column(JSONB, nullable=True)
    result = Column(JSONB, nullable=True)
    attempt_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_text = Column(Text, nullable=True)
    worker_id = Column(String(100), nullable=True)

    __table_args__ = (
        UniqueConstraint("delivery_id", "head_sha", name="uq_review_job_delivery_sha"),
    )

    def __repr__(self):
        return f"<ReviewJob {self.id} PR#{self.pr_number} status={self.status}>"
