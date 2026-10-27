"""Admin API request/response schemas.

Phase 1: authentication. Phase 2: read-only analytics (overview, users,
repositories, reviews). Metric integrity: anything unrecorded is marked
``available: false`` with a reason — never a fabricated zero.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class AdminSessionRead(BaseModel):
    username: str
    expires_at: datetime


AdminLoginResponse = AdminSessionRead


# ---------------------------------------------------------------------------
# Shared metric primitives
# ---------------------------------------------------------------------------


class ScalarMetric(BaseModel):
    available: bool
    value: int | float | str | None = None
    reason: str | None = None


class NumericMetric(BaseModel):
    available: bool
    value: float | None = None
    reason: str | None = None
    sample_size: int | None = None


class PeriodRead(BaseModel):
    key: str
    start: datetime
    end: datetime


# ---------------------------------------------------------------------------
# Overview (§7.1)
# ---------------------------------------------------------------------------


class CredentialProviderBreakdown(BaseModel):
    provider: str
    total: int
    valid: int
    invalid: int
    enabled: int
    disabled: int


class ProviderModelCount(BaseModel):
    provider: str | None
    model: str | None
    count: int


class FailureCategory(BaseModel):
    category: str
    count: int


class ProviderHealthRead(BaseModel):
    provider: str
    status: str
    success_rate: float | None
    circuit_state: str | None
    last_error: str | None
    last_error_at: datetime | None
    snapshot_at: datetime | None


class MaintenanceStateRead(BaseModel):
    enabled: bool
    title: str | None = None
    message: str | None = None
    expected_return_at: str | None = None


class OverviewResponse(BaseModel):
    period: PeriodRead
    users_total: int
    users_new_in_period: int
    signed_in_users: ScalarMetric
    last_login_at: ScalarMetric
    active_users: dict[str, ScalarMetric]
    credentials_total: int
    credentials_by_provider: list[CredentialProviderBreakdown]
    repos_connected: int
    reviews_total: int
    reviews_in_period: int
    reviews_by_status: dict[str, int]
    reviews_by_provider_model: list[ProviderModelCount]
    retries_in_period: int
    duration_p50_ms: NumericMetric
    duration_p95_ms: NumericMetric
    failure_rate: NumericMetric
    failure_categories: list[FailureCategory]
    provider_health: list[ProviderHealthRead]
    maintenance: MaintenanceStateRead
    features: dict[str, str]
    token_usage: ScalarMetric
    cost_totals: ScalarMetric


# ---------------------------------------------------------------------------
# Users (§7.2)
# ---------------------------------------------------------------------------


class AdminUserDisableRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("reason must not be blank")
        return stripped


class AdminUserStatusRead(BaseModel):
    id: uuid.UUID
    status: str
    disabled_at: datetime | None


class AdminRevokeSessionsResponse(BaseModel):
    revoked: bool


class AdminUserListItem(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    github_username: str | None
    created_at: datetime
    last_login_at: datetime | None
    status: str
    repo_count: int
    credential_count: int
    review_count: int


class AdminUserListResponse(BaseModel):
    items: list[AdminUserListItem]
    total: int
    limit: int
    offset: int


class UserRepositoryItem(BaseModel):
    id: uuid.UUID
    full_name: str
    is_private: bool
    is_archived: bool
    removed_at: datetime | None
    last_synced_at: datetime | None
    mapping_provider: str | None
    mapping_model: str | None
    mapping_health: str


class UserCredentialItem(BaseModel):
    id: uuid.UUID
    label: str
    provider: str
    is_valid: bool
    is_enabled: bool
    last_used_at: datetime | None
    created_at: datetime
    last_health_status: str | None
    last_health_at: datetime | None


class UserReviewItem(BaseModel):
    id: uuid.UUID
    status: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    repository_full_name: str
    pr_number: int
    pr_title: str
    latest_provider: str | None
    latest_model: str | None
    latest_status: str | None
    latest_duration_ms: int | None
    latest_error: str | None


class UserErrorItem(BaseModel):
    provider: str | None
    message: str
    occurred_at: datetime | None


class AuditEventItem(BaseModel):
    id: uuid.UUID
    action: str
    actor_id: str | None
    actor_type: str
    outcome: str | None
    created_at: datetime


class UserProfileRead(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    github_username: str | None
    avatar_url: str | None
    role: str
    status: str
    is_verified: bool
    default_provider: str | None
    created_at: datetime
    disabled_at: datetime | None
    last_login_at: datetime | None
    last_active_at: datetime | None


class UserReviewsSection(BaseModel):
    items: list[UserReviewItem]
    total: int
    status_counts: dict[str, int]


class AdminUserDetail(BaseModel):
    profile: UserProfileRead
    repositories: list[UserRepositoryItem]
    credentials: list[UserCredentialItem]
    reviews: UserReviewsSection
    recent_errors: list[UserErrorItem]
    audit_events: list[AuditEventItem]


# ---------------------------------------------------------------------------
# Repositories (§7.3)
# ---------------------------------------------------------------------------


class AdminRepositoryItem(BaseModel):
    id: uuid.UUID
    full_name: str
    is_private: bool
    is_archived: bool
    removed_at: datetime | None
    created_at: datetime
    last_synced_at: datetime | None
    owner_id: uuid.UUID
    owner_email: str
    owner_github_username: str | None
    installation_account_login: str | None
    installation_suspended_at: datetime | None
    installation_permissions_ok: bool | None
    mapping_provider: str | None
    mapping_model: str | None
    mapping_health: str
    review_count: int
    last_review_at: datetime | None
    recent_failures_7d: int


class AdminRepositoryListResponse(BaseModel):
    items: list[AdminRepositoryItem]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Reviews (§7.3)
# ---------------------------------------------------------------------------


class AdminReviewItem(BaseModel):
    id: uuid.UUID
    status: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    repository_id: uuid.UUID
    repository_full_name: str
    pr_number: int
    pr_title: str
    owner_email: str
    configured_provider: str | None
    configured_model: str | None
    provider: str | None
    model: str | None
    execution_status: str | None
    duration_ms: int | None
    error: str | None


class AdminReviewListResponse(BaseModel):
    items: list[AdminReviewItem]
    total: int
    limit: int
    offset: int


class AdminAuditDetails(BaseModel):
    """Whitelisted scalar audit details (kept permissive, never secrets)."""

    model_config = {"extra": "allow"}


# Placeholder to keep the audit shape documented for phase 7's viewer.
AuditEventDetail = AdminAuditDetails | dict[str, Any]


# ---------------------------------------------------------------------------
# Providers / credentials (§9, §10, §18)
# ---------------------------------------------------------------------------


class AdminProviderRead(BaseModel):
    id: uuid.UUID
    name: str
    display_name: str
    slug: str
    default_model: str
    priority: int
    is_enabled: bool
    status: str
    status_message: str | None
    status_expires_at: datetime | None
    allow_key_addition: bool
    supports_streaming: bool
    supports_vision: bool
    supports_function_calling: bool
    supports_reasoning: bool
    # Usage / health aggregates (stored rows only — never fabricated).
    keys_total: int
    keys_enabled: int
    keys_valid: int
    mapped_repositories: int
    models_count: int = 0
    last_health_status: str | None
    last_health_at: datetime | None


class AdminProviderListResponse(BaseModel):
    items: list[AdminProviderRead]


class AdminProviderUpdate(BaseModel):
    status: str | None = None
    status_message: str | None = Field(default=None, max_length=500)
    status_expires_at: datetime | None = None
    is_enabled: bool | None = None
    allow_key_addition: bool | None = None

    @field_validator("status_message")
    @classmethod
    def _strip_message(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        return value or None


class AdminKeyRead(BaseModel):
    """Credential metadata only — never key material (not even masked)."""

    id: uuid.UUID
    user_id: uuid.UUID
    user_email: str
    provider: str
    label: str
    is_valid: bool
    is_enabled: bool
    last_used_at: datetime | None
    created_at: datetime | None


class AdminKeyListResponse(BaseModel):
    items: list[AdminKeyRead]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Maintenance mode (§12)
# ---------------------------------------------------------------------------


class AdminMaintenanceRead(BaseModel):
    """Full internal maintenance state (admin only; `reason` never public)."""

    enabled: bool
    title: str | None = None
    message: str | None = None
    expected_return_at: str | None = None
    reason: str | None = None
    changed_by: str | None = None
    changed_at: str | None = None
    version: int = 0


class AdminMaintenanceUpdate(BaseModel):
    """Whitelisted maintenance update; `version` enables 409 conflict checks."""

    enabled: bool | None = None
    title: str | None = Field(default=None, max_length=200)
    message: str | None = Field(default=None, max_length=1000)
    expected_return_at: str | None = Field(default=None, max_length=100)
    reason: str | None = Field(default=None, max_length=500)
    version: int | None = None

    @field_validator("title", "message", "expected_return_at", "reason")
    @classmethod
    def _strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        return value or None


# ---------------------------------------------------------------------------
# Feature flags (§11)
# ---------------------------------------------------------------------------


class AdminFeatureFlagRead(BaseModel):
    """One canonical flag (missing DB rows are synthesized as `enabled`)."""

    key: str
    status: str = "enabled"
    message: str | None = None


class AdminFeatureFlagUpdate(BaseModel):
    """Flag mutation body (`status` validated against `FLAG_STATUSES`)."""

    status: str
    message: str | None = Field(default=None, max_length=500)

    @field_validator("message")
    @classmethod
    def _strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        return value or None


# ---------------------------------------------------------------------------
# Model overrides (§11.2)
# ---------------------------------------------------------------------------


class AdminModelOverrideRead(BaseModel):
    provider_slug: str
    model_id: str
    status: str = "available"
    message: str | None = None


class AdminModelOverrideUpdate(BaseModel):
    """Upsert (or clear with `status='available'`) one model override."""

    provider_slug: str = Field(min_length=1, max_length=50)
    model_id: str = Field(min_length=1, max_length=200)
    status: str
    message: str | None = Field(default=None, max_length=500)

    @field_validator("provider_slug", "model_id")
    @classmethod
    def _require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("message")
    @classmethod
    def _strip_message(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        return value or None


# ---------------------------------------------------------------------------
# Announcements (§13)
# ---------------------------------------------------------------------------


class AdminAnnouncementRead(BaseModel):
    """Full announcement row (admin view, includes drafts and schedule)."""

    id: uuid.UUID
    title: str
    message: str
    kind: str
    state: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    link_url: str | None = None
    link_label: str | None = None
    is_enabled: bool
    is_dismissible: bool
    created_by: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AdminAnnouncementCreate(BaseModel):
    """Create body; schedule/link/kind validated in `services.announcements`."""

    title: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=2000)
    kind: str = "general"
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    link_url: str | None = Field(default=None, max_length=500)
    link_label: str | None = Field(default=None, max_length=100)
    is_enabled: bool | None = None
    is_dismissible: bool | None = None

    @field_validator("title", "message")
    @classmethod
    def _require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("link_url", "link_label")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        return value or None


class AdminAnnouncementUpdate(BaseModel):
    """Partial update body; omitted fields are left unchanged.

    Explicit ``null`` clears the nullable schedule/link fields; ``state``
    flips between ``draft`` and ``published`` (audited distinctly).
    """

    title: str | None = Field(default=None, min_length=1, max_length=200)
    message: str | None = Field(default=None, min_length=1, max_length=2000)
    kind: str | None = None
    state: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    link_url: str | None = Field(default=None, max_length=500)
    link_label: str | None = Field(default=None, max_length=100)
    is_enabled: bool | None = None
    is_dismissible: bool | None = None

    @field_validator("title", "message")
    @classmethod
    def _require_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("link_url", "link_label")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        return value or None


# ---------------------------------------------------------------------------
# Audit log viewer (§16)
# ---------------------------------------------------------------------------


class AdminAuditLogItem(BaseModel):
    """One audit row, including safe scalar details (never secrets, B29)."""

    id: uuid.UUID
    actor_id: str | None = None
    actor_type: str | None = None
    action: str
    entity_type: str
    entity_id: str
    outcome: str | None = None
    details: dict[str, Any] | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime


class AdminAuditListResponse(BaseModel):
    items: list[AdminAuditLogItem]
    total: int
