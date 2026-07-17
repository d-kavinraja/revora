"""Health, failover, and observability tables.

Revision ID: h34lth_f4ll0v3r
Revises: tk3n_us4g3_c0st
Create Date: 2026-07-16 13:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "h34lth_f4ll0v3r"
down_revision = "tk3n_us4g3_c0st"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # provider_health table
    op.create_table(
        "provider_health",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("avg_latency_ms", sa.Float(), server_default="0"),
        sa.Column("success_rate", sa.Float(), server_default="1"),
        sa.Column("error_rate", sa.Float(), server_default="0"),
        sa.Column("total_requests", sa.Integer(), server_default="0"),
        sa.Column("failed_requests", sa.Integer(), server_default="0"),
        sa.Column("circuit_state", sa.String(20), server_default="closed"),
        sa.Column("circuit_opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_provider_health_provider", "provider_health", ["provider"])

    # failover_log table
    op.create_table(
        "failover_log",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("feature", sa.String(50), nullable=False),
        sa.Column("failed_provider", sa.String(50), nullable=False),
        sa.Column("failed_model", sa.String(100), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=False),
        sa.Column("fallback_provider", sa.String(50), nullable=False),
        sa.Column("fallback_model", sa.String(100), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("total_latency_ms", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_failover_log_user_id", "failover_log", ["user_id"])

    # llm_request_log table
    op.create_table(
        "llm_request_log",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("request_id", sa.String(64), unique=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("feature", sa.String(50), nullable=False),
        sa.Column("messages_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("response_hash", sa.String(64), nullable=True),
        sa.Column("error_type", sa.String(50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("was_fallback", sa.Boolean(), server_default="false"),
        sa.Column("original_provider", sa.String(50), nullable=True),
        sa.Column("attempt_number", sa.Integer(), server_default="1"),
        sa.Column(
            "api_key_id",
            sa.Uuid(),
            sa.ForeignKey("api_keys.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_llm_request_log_user_id", "llm_request_log", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_request_log_user_id", table_name="llm_request_log")
    op.drop_table("llm_request_log")
    op.drop_index("ix_failover_log_user_id", table_name="failover_log")
    op.drop_table("failover_log")
    op.drop_index("ix_provider_health_provider", table_name="provider_health")
    op.drop_table("provider_health")
