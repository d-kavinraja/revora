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
    ForeignKey,
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
    "botaniq",
    "api_keys_add",
    "routing_mapping",
    "review_initiation",
    "reviews",
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

#: How often a published announcement may reappear for a given subject.
#:
#: - ``once_until_dismissed``: stays visible until the subject dismisses it.
#:   A published-content update bumps ``Announcement.version``, which makes
#:   the announcement eligible again for everyone who dismissed the old
#:   version.
#: - ``every_login``: shown once per login session; the next login makes it
#:   eligible again.
#: - ``recurring``: after dismissal it reappears once the configured
#:   interval has elapsed.
ANNOUNCEMENT_DISPLAY_POLICIES = (
    "once_until_dismissed",
    "every_login",
    "recurring",
)

#: Reserved audience vocabulary. ``all`` is the only active value today —
#: the column exists so targeting can be activated without a schema change.
ANNOUNCEMENT_AUDIENCES = ("all", "authenticated", "anonymous")

#: Dismissal subject kinds (§13 dismissal isolation).
ANNOUNCEMENT_SUBJECT_TYPES = ("user", "device")


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
        String(50), default="general", server_default="general", nullable=False
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
    #: Published-content revision. Bumped on any content-affecting admin
    #: edit (or a transition into ``published``). Dismissal state is keyed
    #: by (announcement, version), so a bump makes the announcement
    #: eligible again for subjects that dismissed the previous version.
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    #: One of ``ANNOUNCEMENT_DISPLAY_POLICIES``.
    display_policy: Mapped[str] = mapped_column(
        String(20),
        default="every_login",
        server_default="every_login",
        nullable=False,
    )
    #: Reappearance interval in minutes. Required (>0) only for the
    #: ``recurring`` policy.
    recur_interval_minutes: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    #: Reserved targeting vocabulary (``all`` today).
    audience: Mapped[str] = mapped_column(
        String(20), default="all", server_default="all", nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )


class AnnouncementState(Base):
    """Per-subject announcement dismissal / seen state (§13).

    A *subject* is either a signed-in user (``subject_type='user'``) or an
    anonymous browser device (``subject_type='device'``). One subject's
    dismissal never affects another subject — not another user, and not a
    different browser.

    Rows are keyed by ``(subject, announcement, announcement_version)``: a
    version bump on the announcement invalidates prior dismissals, so the
    updated content becomes eligible again.
    """

    __tablename__ = "announcement_states"
    __table_args__ = (
        UniqueConstraint(
            "subject_type",
            "subject_id",
            "announcement_id",
            "announcement_version",
            name="uq_announcement_states_subject_announcement_version",
        ),
        Index(
            "ix_announcement_states_subject",
            "subject_type",
            "subject_id",
        ),
        Index(
            "ix_announcement_states_announcement",
            "announcement_id",
        ),
    )

    subject_type: Mapped[str] = mapped_column(String(10), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(64), nullable=False)
    announcement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("announcements.id", ondelete="CASCADE"),
        nullable=False,
    )
    announcement_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    dismissed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
