"""Token usage and cost budget tables.

Revision ID: tk3n_us4g3_c0st
Revises: pr0v1d3r_r3g1stry
Create Date: 2026-07-16 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "tk3n_us4g3_c0st"
down_revision = "pr0v1d3r_r3g1stry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # llm_token_usage table
    op.create_table(
        "llm_token_usage",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column(
            "api_key_id",
            sa.Uuid(),
            sa.ForeignKey("api_keys.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("input_cost_usd", sa.Float(), nullable=False),
        sa.Column("output_cost_usd", sa.Float(), nullable=False),
        sa.Column("total_cost_usd", sa.Float(), nullable=False),
        sa.Column("feature", sa.String(50), nullable=False),
        sa.Column(
            "review_id",
            sa.Uuid(),
            sa.ForeignKey("reviews.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("is_fallback", sa.Boolean(), server_default="false"),
        sa.Column("cached", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_token_usage_user_date", "llm_token_usage", ["user_id", "created_at"])
    op.create_index("ix_token_usage_provider", "llm_token_usage", ["provider"])

    # cost_budgets table
    op.create_table(
        "cost_budgets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("budget_type", sa.String(20), nullable=False),
        sa.Column("limit_usd", sa.Float(), nullable=False),
        sa.Column("spent_usd", sa.Float(), server_default="0"),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.Column("feature", sa.String(50), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("reset_at", sa.String(30), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("cost_budgets")
    op.drop_index("ix_token_usage_provider", table_name="llm_token_usage")
    op.drop_index("ix_token_usage_user_date", table_name="llm_token_usage")
    op.drop_table("llm_token_usage")
