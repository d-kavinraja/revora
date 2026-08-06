# ruff: noqa: F821
from typing import Any

from sqlalchemy import BigInteger, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import JSON_TYPE, Base


class User(Base):
    __tablename__ = "users"

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
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE, default=dict, server_default="{}"
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
