"""drop_review_execution_contexts_unique

Revision ID: 20260731_1200
Revises: 20260731_1100
Create Date: 2026-07-31

Drops the unique index on review_execution_contexts.review_id.

With ONE reviews row per pull request lifecycle, every execution
(rerun / retry / restart / new-commit webhook) inserts its own immutable
execution context row. The previous 1:1 mapping between review rows and
contexts no longer holds, so the constraint is removed (the FK stays).
"""

from alembic import op

revision = "20260731_1200"
down_revision = "20260731_1100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_review_execution_contexts_review_id", table_name="review_execution_contexts")


def downgrade() -> None:
    op.create_index(
        "ix_review_execution_contexts_review_id",
        "review_execution_contexts",
        ["review_id"],
        unique=True,
    )
