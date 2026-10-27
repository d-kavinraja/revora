"""Platform control-plane tables: settings, feature flags, announcements,
per-model overrides. All reads are default-tolerant: a missing row means
"default behavior" (enabled / available), matching the SQLite `create_all`
dev path where the seed migration never runs.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import JSON_TYPE, Base

# Value vocabulary shared by feature flags, provider statuses and model
# overrides (validation lives in the API layer; these constants keep the
# vocabulary in one place).
FLAG_STATUSES = (
    "enabled",
    "disabled",
    "maintenance",
    "coming_soon",
    "under_testing",
)

#: Canonical feature-flag keys (§11.1). Seeded as `enabled` by migration
#: `adm1n_s33d`; a missing row is treated as `enabled` everywhere.
FEATURE_FLAG_KEYS = (
    "model_lab",
    "mouthmap",
    "api_keys_add",
    "routing_mapping",
    "review_initiation",
    "usage",
    "analytics",
    "guide",
)

#: Per-model override statuses (§11.2). `available` means "no override" —
#: clearing an override restores the model with no user action.
MODEL_OVERRIDE_STATUSES = ("available", "disabled")

#: Announcement kind vocabulary (§13.1).
ANNOUNCEMENT_KINDS = (
    "scheduled_maintenance",
    "upgrade",
    "service_interruption",
    "new_feature",
    "provider_update",
    "general",
)

#: Announcement lifecycle states (§13.2): drafts are never public (B28).
ANNOUNCEMENT_STATES = ("draft", "published")


class PlatformSetting(Base):
    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, nullable=False
    )
    value: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE, default=dict, server_default="{}", nullable=False
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )


class FeatureFlag(Base):
    __tablename__ = "feature_flags"

    key: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default="enabled", server_default="enabled", nullable=False
    )
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )


class Announcement(Base):
    __tablename__ = "announcements"
    # Public-payload filter: published + enabled + active window.
    __table_args__ = (
        Index(
            "ix_announcements_publication",
            "state",
            "is_enabled",
            "starts_at",
            "ends_at",
        ),
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(
        String(20), default="info", server_default="info", nullable=False
    )
    state: Mapped[str] = mapped_column(
        String(20), default="draft", server_default="draft", nullable=False
    )
    starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    link_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    link_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    is_dismissible: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )


class ModelOverride(Base):
    __tablename__ = "model_overrides"
    __table_args__ = (
        UniqueConstraint(
            "provider_slug",
            "model_id",
            name="uq_model_overrides_provider_slug_model_id",
        ),
    )

    provider_slug: Mapped[str] = mapped_column(String(50), nullable=False)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="available", server_default="available", nullable=False
    )
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
