"""Admin control plane schema: admin auth, platform settings, flags, notices.

Revision ID: adm1n_sch3ma
Revises: s3c8t0k3nv1r
Create Date: 2026-10-17 12:00:00.000000

Additive-only migration (zero behavior change on deploy):
- new tables: admin_users, admin_sessions, platform_settings, feature_flags,
  announcements, model_overrides
- additive columns with server defaults: provider_registry, api_keys, users
- analytics/list indexes on users and review_executions

Legacy rows are untouched; `alembic downgrade -1` drops only these additions.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "adm1n_sch3ma"
down_revision: str | None = "s3c8t0k3nv1r"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = sa.JSON().with_variant(postgresql.JSONB, "postgresql")


def upgrade() -> None:
    # --- admin authentication ---------------------------------------------
    op.create_table(
        "admin_users",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "failed_login_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_admin_users_username", "admin_users", ["username"], unique=True
    )

    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("admin_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_admin_sessions_token_hash"),
        sa.ForeignKeyConstraint(
            ["admin_id"], ["admin_users.id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_admin_sessions_admin_id", "admin_sessions", ["admin_id"])
    op.create_index(
        "ix_admin_sessions_expires_at", "admin_sessions", ["expires_at"]
    )

    # --- platform control plane -------------------------------------------
    op.create_table(
        "platform_settings",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", JSONB, server_default="{}", nullable=False),
        sa.Column("updated_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_index(
        "ix_platform_settings_key", "platform_settings", ["key"], unique=True
    )

    op.create_table(
        "feature_flags",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column(
            "status", sa.String(20), server_default="enabled", nullable=False
        ),
        sa.Column("message", sa.String(500), nullable=True),
        sa.Column("updated_by", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_index("ix_feature_flags_key", "feature_flags", ["key"], unique=True)

    op.create_table(
        "announcements",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(20), server_default="info", nullable=False),
        sa.Column("state", sa.String(20), server_default="draft", nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("link_url", sa.String(500), nullable=True),
        sa.Column("link_label", sa.String(100), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "is_dismissible", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_announcements_publication",
        "announcements",
        ["state", "is_enabled", "starts_at", "ends_at"],
    )

    op.create_table(
        "model_overrides",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("provider_slug", sa.String(50), nullable=False),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column(
            "status", sa.String(20), server_default="available", nullable=False
        ),
        sa.Column("message", sa.String(500), nullable=True),
        sa.UniqueConstraint(
            "provider_slug",
            "model_id",
            name="uq_model_overrides_provider_slug_model_id",
        ),
    )

    # --- additive columns (server defaults keep legacy rows valid) --------
    op.add_column(
        "provider_registry",
        sa.Column(
            "status", sa.String(20), server_default="available", nullable=False
        ),
    )
    op.add_column(
        "provider_registry",
        sa.Column("status_message", sa.String(500), nullable=True),
    )
    op.add_column(
        "provider_registry",
        sa.Column("status_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "provider_registry",
        sa.Column(
            "allow_key_addition", sa.Boolean(), server_default="true", nullable=False
        ),
    )
    op.add_column(
        "api_keys",
        sa.Column("is_enabled", sa.Boolean(), server_default="true", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
    )
    op.add_column(
        "users", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users", sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True)
    )

    # --- analytics/list indexes -------------------------------------------
    op.create_index("ix_users_created_at", "users", ["created_at"])
    op.create_index("ix_users_last_login_at", "users", ["last_login_at"])
    op.create_index("ix_users_status", "users", ["status"])
    op.create_index(
        "ix_review_executions_started_at", "review_executions", ["started_at"]
    )
    op.create_index(
        "ix_review_executions_status", "review_executions", ["status"]
    )
    op.create_index(
        "ix_review_executions_provider", "review_executions", ["provider"]
    )


def downgrade() -> None:
    op.drop_index("ix_review_executions_provider", table_name="review_executions")
    op.drop_index("ix_review_executions_status", table_name="review_executions")
    op.drop_index("ix_review_executions_started_at", table_name="review_executions")
    op.drop_index("ix_users_status", table_name="users")
    op.drop_index("ix_users_last_login_at", table_name="users")
    op.drop_index("ix_users_created_at", table_name="users")

    op.drop_column("users", "last_active_at")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "disabled_at")
    op.drop_column("users", "status")
    op.drop_column("api_keys", "is_enabled")
    op.drop_column("provider_registry", "allow_key_addition")
    op.drop_column("provider_registry", "status_expires_at")
    op.drop_column("provider_registry", "status_message")
    op.drop_column("provider_registry", "status")

    op.drop_table("model_overrides")
    op.drop_index("ix_announcements_publication", table_name="announcements")
    op.drop_table("announcements")
    op.drop_index("ix_feature_flags_key", table_name="feature_flags")
    op.drop_table("feature_flags")
    op.drop_index("ix_platform_settings_key", table_name="platform_settings")
    op.drop_table("platform_settings")
    op.drop_index("ix_admin_sessions_expires_at", table_name="admin_sessions")
    op.drop_index("ix_admin_sessions_admin_id", table_name="admin_sessions")
    op.drop_table("admin_sessions")
    op.drop_index("ix_admin_users_username", table_name="admin_users")
    op.drop_table("admin_users")
