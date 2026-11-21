"""Add per-tab kLLM user presence.

Revision ID: kllm02_user_presence
Revises: onbd01_onboarding_completed
Create Date: 2026-11-21 01:00:00.000000

Additive-only. This table is presence telemetry, not an authentication session
store: JWT expiry/token_version remain authoritative for identity.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "kllm02_user_presence"
down_revision: str | None = "onbd01_onboarding_completed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_presence_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("client_session_id", sa.String(length=64), nullable=False),
        sa.Column("token_jti_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_presence_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_user_presence_sessions")
        ),
    )
    op.create_index(
        op.f("ix_user_presence_active_last_seen"),
        "user_presence_sessions",
        ["active", "last_seen_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_presence_expires_at"),
        "user_presence_sessions",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("uq_user_presence_user_client"),
        "user_presence_sessions",
        ["user_id", "client_session_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("uq_user_presence_user_client"),
        table_name="user_presence_sessions",
    )
    op.drop_index(
        op.f("ix_user_presence_expires_at"),
        table_name="user_presence_sessions",
    )
    op.drop_index(
        op.f("ix_user_presence_active_last_seen"),
        table_name="user_presence_sessions",
    )
    op.drop_table("user_presence_sessions")
