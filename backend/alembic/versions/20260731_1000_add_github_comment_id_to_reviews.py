"""add_github_comment_id_to_reviews

Revision ID: 20260731_1000
Revises: 20260730_1600
Create Date: 2026-07-31

Adds github_comment_id column to reviews table so the pipeline can
track the single top-level GitHub comment holding the review summary.
On reruns, this comment is EDITED (PATCH) instead of posting a new
duplicate comment for the same pull request.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260731_1000"
down_revision = "20260730_1600"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reviews",
        sa.Column("github_comment_id", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reviews", "github_comment_id")
