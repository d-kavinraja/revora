# ruff: noqa: F821
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import JSON_TYPE, Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_created_at", "created_at"),)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    github_id: Mapped[int | None] = mapped_column(
        BigInteger, unique=True, index=True, nullable=True
    )
    github_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="user", nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    token_version: Mapped[int] = mapped_column(
        default=0, server_default="0", nullable=False
    )
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE, default=dict, server_default="{}"
    )

    # Admin control plane (schema migrated in adm1n_sch3ma; behavior wired in
    # phases 3 and 7 — status enforcement, login/activity instrumentation).
    status: Mapped[str] = mapped_column(
        String(20), default="active", server_default="active", nullable=False
    )
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_active_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    api_keys: Mapped[list["ApiKey"]] = relationship(
        "ApiKey", back_populates="user", cascade="all, delete-orphan"
    )
    org_memberships: Mapped[list["OrgMember"]] = relationship(
        "OrgMember",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="[OrgMember.user_id]",
    )
