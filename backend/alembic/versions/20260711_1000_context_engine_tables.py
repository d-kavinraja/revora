"""context engine tables

Revision ID: c0nt3xt_3ng1n3
Revises: bfd39850f721
Create Date: 2026-07-11 10:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "c0nt3xt_3ng1n3"
down_revision: Union[str, None] = "bfd39850f721"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "repository_knowledge",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("repo_id", UUID(as_uuid=True), sa.ForeignKey("repositories.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("knowledge_type", sa.String(50), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "repository_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("repo_id", UUID(as_uuid=True), sa.ForeignKey("repositories.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("rule_type", sa.String(50), nullable=False),
        sa.Column("rule_text", sa.Text, nullable=False),
        sa.Column("priority", sa.Integer, server_default="0"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "repository_indexes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("repo_id", UUID(as_uuid=True), sa.ForeignKey("repositories.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("index_data", JSONB, nullable=False),
        sa.Column("graphs", JSONB, server_default="{}"),
        sa.Column("commit_sha", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "repository_intelligence",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("repo_id", UUID(as_uuid=True), sa.ForeignKey("repositories.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("intelligence_data", JSONB, nullable=False),
        sa.Column("commit_sha", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "review_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("review_id", UUID(as_uuid=True), sa.ForeignKey("reviews.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("stage", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("message", sa.Text, nullable=True),
        sa.Column("metrics", JSONB, server_default="{}"),
        sa.Column("progress", sa.Float, nullable=True),
        sa.Column("duration_ms", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "review_metrics",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("review_id", UUID(as_uuid=True), sa.ForeignKey("reviews.id", ondelete="CASCADE"), index=True, nullable=False, unique=True),
        sa.Column("repository_size_bytes", sa.BigInteger, nullable=True),
        sa.Column("files_scanned", sa.Integer, nullable=True),
        sa.Column("files_changed", sa.Integer, nullable=True),
        sa.Column("files_retrieved", sa.Integer, nullable=True),
        sa.Column("dependencies_indexed", sa.Integer, nullable=True),
        sa.Column("ast_nodes_parsed", sa.Integer, nullable=True),
        sa.Column("context_files_selected", sa.Integer, nullable=True),
        sa.Column("prompt_size_tokens", sa.Integer, nullable=True),
        sa.Column("input_tokens", sa.Integer, nullable=True),
        sa.Column("output_tokens", sa.Integer, nullable=True),
        sa.Column("estimated_cost_usd", sa.Float, nullable=True),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("total_duration_ms", sa.Float, nullable=True),
        sa.Column("stages", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("review_metrics")
    op.drop_table("review_events")
    op.drop_table("repository_intelligence")
    op.drop_table("repository_indexes")
    op.drop_table("repository_rules")
    op.drop_table("repository_knowledge")
