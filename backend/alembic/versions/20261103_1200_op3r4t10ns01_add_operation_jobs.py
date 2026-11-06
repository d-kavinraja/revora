"""add operation jobs and per-user health metadata

Revision ID: op3r4t10ns01
Revises: c77fb53c4efc
Create Date: 2026-11-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "op3r4t10ns01"
down_revision: Union[str, None] = "c77fb53c4efc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    op.add_column(
        "provider_health",
        sa.Column("user_id", sa.Uuid(), nullable=True),
    )

    if bind.dialect.name == "postgresql":
        op.execute(
            """
            DELETE FROM provider_health a
            USING provider_health b
            WHERE a.id < b.id
              AND COALESCE(a.user_id::text, '') = COALESCE(b.user_id::text, '')
              AND a.provider = b.provider
            """
        )
    op.add_column(
        "provider_health",
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "provider_health",
        sa.Column("last_latency_ms", sa.Float(), nullable=True),
    )
    op.add_column(
        "provider_health",
        sa.Column("last_model", sa.String(length=200), nullable=True),
    )
    op.create_foreign_key(
        "fk_provider_health_user_id_users",
        "provider_health",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_provider_health_user_id", "provider_health", ["user_id"], unique=False
    )
    op.create_unique_constraint(
        "uq_provider_health_user_provider",
        "provider_health",
        ["user_id", "provider"],
    )

    op.add_column(
        "api_key_health",
        sa.Column("model_name", sa.String(length=200), nullable=True),
    )

    op.create_table(
        "operation_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("operation_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column(
            "payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column(
            "result",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("progress_current", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("worker_id", sa.String(length=100), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("active_dedupe_key", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_operation_jobs_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_operation_jobs"),
        sa.UniqueConstraint(
            "active_dedupe_key", name="uq_operation_jobs_active_dedupe_key"
        ),
    )
    op.create_index(
        "ix_operation_jobs_status_available_at",
        "operation_jobs",
        ["status", "available_at"],
        unique=False,
    )
    op.create_index(
        "ix_operation_jobs_user_id_created_at",
        "operation_jobs",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_operation_jobs_user_id_created_at", table_name="operation_jobs")
    op.drop_index("ix_operation_jobs_status_available_at", table_name="operation_jobs")
    op.drop_table("operation_jobs")
    op.drop_column("api_key_health", "model_name")
    op.drop_constraint("uq_provider_health_user_provider", "provider_health", type_="unique")
    op.drop_index("ix_provider_health_user_id", table_name="provider_health")
    op.drop_constraint("fk_provider_health_user_id_users", "provider_health", type_="foreignkey")
    op.drop_column("provider_health", "last_model")
    op.drop_column("provider_health", "last_latency_ms")
    op.drop_column("provider_health", "last_checked_at")
    op.drop_column("provider_health", "user_id")
