# ruff: noqa: F821
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import JSON_TYPE, Base


class Review(Base):
    __tablename__ = "reviews"

    pr_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pull_requests.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    github_check_run_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # The single top-level GitHub comment holding this review's summary.
    # Reused (edited) on reruns so the PR never accumulates duplicate Revora comments.
    github_comment_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Relationships
    pull_request: Mapped["PullRequest"] = relationship("PullRequest")
    comments: Mapped[list["ReviewComment"]] = relationship(
        "ReviewComment", back_populates="review", cascade="all, delete-orphan"
    )


class ReviewComment(Base):
    __tablename__ = "review_comments"

    review_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"), index=True, nullable=False
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    line_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    body: Mapped[str] = mapped_column(String, nullable=False)
    comment_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # e.g. bug, security, performance
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # e.g. low, medium, high, critical

    # Relationships
    review: Mapped["Review"] = relationship("Review", back_populates="comments")
