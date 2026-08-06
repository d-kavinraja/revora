"""Add missing review_id column to llm_request_log.

Revision ID: 20260730_1400
Revises: 20260730_1300
Create Date: 2026-07-30

The LLMRequestLog model expects a review_id FK column that was
missing from the original migration. This adds it.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260730_1400"
down_revision = "20260730_1300"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("llm_request_log")]
    if "review_id" not in columns:
        op.add_column(
            "llm_request_log",
            sa.Column(
                "review_id",
                sa.Uuid(),
                sa.ForeignKey("reviews.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index(
            "ix_llm_request_log_review_id", "llm_request_log", ["review_id"]
        )


def downgrade() -> None:
    op.drop_index("ix_llm_request_log_review_id", table_name="llm_request_log")
    op.drop_column("llm_request_log", "review_id")
