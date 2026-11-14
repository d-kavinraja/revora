"""Public platform status schemas (phase 5, §17).

`GET /api/v1/platform/status` is unauthenticated — these models are the
public contract: maintenance copy (never the internal reason), feature-flag
statuses and blocked-provider explanations only. Phase 7 adds the public
announcement feed (§13): published + active rows only, no internal fields.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel


class PublicMaintenanceState(BaseModel):
    enabled: bool
    title: str | None = None
    message: str | None = None
    expected_return_at: str | None = None


class DisabledProviderRead(BaseModel):
    """User-facing explanation for a provider that blocks new work (§9.3)."""

    slug: str
    message: str | None = None
    expires_at: datetime | None = None


class PublicFeatureState(BaseModel):
    """One feature flag for the user app (§11.1): status + admin message."""

    status: str = "enabled"
    message: str | None = None


class PublicAnnouncementRead(BaseModel):
    """One published, currently-active announcement for the user app (§13).

    User-facing fields only — no `state`, `is_enabled`, `created_by`; the
    public feed only ever contains rows that passed the publication filter
    and the calling subject's visibility policy.
    """

    id: uuid.UUID
    title: str
    message: str
    kind: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    link_url: str | None = None
    link_label: str | None = None
    is_dismissible: bool = True
    #: Published-content revision. A bumped version invalidates prior
    #: dismissals, so updated content becomes eligible again.
    version: int = 1
    #: One of: once_until_dismissed | every_login | recurring.
    display_policy: str = "every_login"
    #: Reappearance interval in minutes (recurring policy only).
    recur_interval_minutes: int | None = None
    #: Reserved targeting vocabulary.
    audience: str = "all"
    #: Whether the calling subject has already dismissed this version.
    dismissed: bool = False


class PublicPlatformStatus(BaseModel):
    maintenance: PublicMaintenanceState
    features: dict[str, str] = {}
    disabled_providers: list[DisabledProviderRead] = []
