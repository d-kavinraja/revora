"""prompt builder tables

Revision ID: pr0mpt_bu1ld3r
Revises: c0nt3xt_3ng1n3
Create Date: 2026-07-16 10:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "pr0mpt_bu1ld3r"
down_revision: Union[str, None] = "c0nt3xt_3ng1n3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prompt_templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("review_type", sa.String(50), nullable=False),
        sa.Column("system_prompt_hash", sa.String(64), nullable=False),
        sa.Column("sections_config", JSONB, server_default="{}"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_prompt_templates_review_type", "prompt_templates", ["review_type"])

    op.create_table(
        "prompt_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("template_id", UUID(as_uuid=True), sa.ForeignKey("prompt_templates.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("version", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("prompt_hash", sa.String(64), nullable=False),
        sa.Column("system_prompt", sa.Text, nullable=False),
        sa.Column("sections_config", JSONB, server_default="{}"),
        sa.Column("token_budget", sa.Integer, server_default="10000"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_prompt_versions_version", "prompt_versions", ["version"])

    op.create_table(
        "prompt_cache",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("cache_key", sa.String(64), nullable=False, unique=True),
        sa.Column("prompt_hash", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("total_tokens", sa.Integer, nullable=False),
        sa.Column("sections_data", JSONB, server_default="{}"),
        sa.Column("ttl_seconds", sa.Integer, server_default="300"),
        sa.Column("hit_count", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "prompt_metrics",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("prompt_id", sa.String(64), nullable=False),
        sa.Column("review_type", sa.String(50), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("total_tokens", sa.Integer, nullable=False),
        sa.Column("prompt_size_bytes", sa.Integer, nullable=False),
        sa.Column("compression_ratio", sa.Float, server_default="1.0"),
        sa.Column("build_time_ms", sa.Float, server_default="0.0"),
        sa.Column("cache_hit", sa.Boolean, server_default="false"),
        sa.Column("estimated_cost_usd", sa.Float, server_default="0.0"),
        sa.Column("sections_count", sa.Integer, server_default="0"),
        sa.Column("files_included", sa.Integer, server_default="0"),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_prompt_metrics_prompt_id", "prompt_metrics", ["prompt_id"])

    op.create_table(
        "token_usage",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("prompt_id", sa.String(64), nullable=False),
        sa.Column("review_type", sa.String(50), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=True),
        sa.Column("budget_limit", sa.Integer, nullable=False),
        sa.Column("budget_used", sa.Float, nullable=False),
        sa.Column("section_usage", JSONB, server_default="{}"),
        sa.Column("estimated_cost_usd", sa.Float, server_default="0.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_token_usage_prompt_id", "token_usage", ["prompt_id"])


def downgrade() -> None:
    op.drop_table("token_usage")
    op.drop_table("prompt_metrics")
    op.drop_table("prompt_cache")
    op.drop_table("prompt_versions")
    op.drop_table("prompt_templates")
