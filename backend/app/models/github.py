# ruff: noqa: F821
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import JSON_TYPE, Base


class Installation(Base):
    __tablename__ = "installations"

    installation_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, index=True, nullable=False
    )
    account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    account_login: Mapped[str] = mapped_column(String(100), nullable=False)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    repository_selection: Mapped[str] = mapped_column(String(20), nullable=False)
    permissions: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    events: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # True while the installation has every permission Revora needs to review.
    # When False, repos under this installation are gated (status "permission_required").
    permissions_ok: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Last sync pass state for this installation (powers the UI "last synchronized" line).
    last_sync_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_sync_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_sync_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(String, nullable=True)
    last_sync_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User")
    repositories: Mapped[list["Repository"]] = relationship(
        "Repository", back_populates="installation"
    )


class Repository(Base):
    __tablename__ = "repositories"

    github_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(500), index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_private: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    installation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("installations.id", ondelete="SET NULL"), index=True, nullable=True
    )
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), index=True, nullable=True
    )
    reviews_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE, default=dict, server_default="{}"
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Set when the repository is removed from the GitHub App installation.
    # The row and all history (PRs, reviews, executions) are preserved.
    removed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Mirrors GitHub's archived flag; archived repos are skipped for new reviews.
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    installation: Mapped[Optional["Installation"]] = relationship(
        "Installation", back_populates="repositories"
    )
    pull_requests: Mapped[list["PullRequest"]] = relationship(
        "PullRequest", back_populates="repository", cascade="all, delete-orphan"
    )


class PullRequest(Base):
    __tablename__ = "pull_requests"

    repo_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True, nullable=False
    )
    pr_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    author: Mapped[str] = mapped_column(String(100), nullable=False)
    head_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    base_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    head_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    additions: Mapped[int] = mapped_column(Integer, default=0)
    deletions: Mapped[int] = mapped_column(Integer, default=0)
    changed_files: Mapped[int] = mapped_column(Integer, default=0)
    github_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    repository: Mapped["Repository"] = relationship(
        "Repository", back_populates="pull_requests"
    )
