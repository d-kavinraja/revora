"""add_repository_lifecycle_tables

Revision ID: 20260730_1300
Revises: 202607301200
Create Date: 2026-07-30

Adds audit_logs, review_timelines, and review_execution_contexts tables
to support repository management and review lifecycle tracking.
"""

import uuid
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260730_1300"
down_revision = "202607301200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- audit_logs ---
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), primary_key=True, default=uuid.uuid4),
        sa.Column("actor_id", sa.String(100), nullable=True),
        sa.Column("actor_type", sa.String(20), nullable=False, server_default="user"),
        sa.Column("action", sa.String(100), nullable=False, index=True),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.String(100), nullable=False, index=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- review_timelines ---
    op.create_table(
        "review_timelines",
        sa.Column("id", sa.Uuid(), primary_key=True, default=uuid.uuid4),
        sa.Column("review_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("stage", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="waiting"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("message", sa.String(500), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- review_execution_contexts ---
    op.create_table(
        "review_execution_contexts",
        sa.Column("id", sa.Uuid(), primary_key=True, default=uuid.uuid4),
        sa.Column("review_id", sa.Uuid(), nullable=False, unique=True, index=True),
        sa.Column("repository_full_name", sa.String(500), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("api_key_id", sa.Uuid(), nullable=True),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("commit_sha", sa.String(40), nullable=False),
        sa.Column("base_branch", sa.String(255), nullable=True),
        sa.Column("head_branch", sa.String(255), nullable=True),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("configuration_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("review_execution_contexts")
    op.drop_table("review_timelines")
    op.drop_table("audit_logs")
