"""add_review_lineage

Revision ID: 20260730_1500
Revises: 20260730_1400
Create Date: 2026-07-30

Adds parent_review_id column to reviews table to establish
review lineage (retry → rerun → restart chain).

Also adds updated_at to review_timelines for ordering.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260730_1500"
down_revision = "20260730_1400"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reviews",
        sa.Column(
            "parent_review_id",
            sa.Uuid(),
            sa.ForeignKey("reviews.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    op.add_column(
        "review_timelines",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reviews", "parent_review_id")
    op.drop_column("review_timelines", "updated_at")
