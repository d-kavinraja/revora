import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy import String, ForeignKey, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, JSON_TYPE

class Review(Base):
    __tablename__ = "reviews"

    pr_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pull_requests.id", ondelete="CASCADE"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    stats: Mapped[Dict[str, Any]] = mapped_column(JSON_TYPE, default=dict, server_default='{}')
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Relationships
    pull_request: Mapped["PullRequest"] = relationship("PullRequest")
    comments: Mapped[List["ReviewComment"]] = relationship("ReviewComment", back_populates="review", cascade="all, delete-orphan")


class ReviewComment(Base):
    __tablename__ = "review_comments"

    review_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), index=True, nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    line_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    body: Mapped[str] = mapped_column(String, nullable=False)
    comment_type: Mapped[str] = mapped_column(String(50), nullable=False) # e.g. bug, security, performance
    severity: Mapped[str] = mapped_column(String(20), nullable=False) # e.g. low, medium, high, critical

    # Relationships
    review: Mapped["Review"] = relationship("Review", back_populates="comments")
