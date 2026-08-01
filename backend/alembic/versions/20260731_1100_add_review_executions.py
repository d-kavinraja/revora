"""add_review_executions

Revision ID: 20260731_1100
Revises: 20260731_1000
Create Date: 2026-07-31

Adds the review_executions table so each run of a review lifecycle
(rerun / retry / restart / new-commit webhook) is tracked separately
while the reviews table holds ONE row per pull request lifecycle.

Also drops the parent_review_id column — review lineage is now tracked
via review_executions instead of chained review rows.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB

revision = "20260731_1100"
down_revision = "20260731_1000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_executions",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "review_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("reviews.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("execution_number", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False, server_default="webhook"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("provider", sa.String(length=100), nullable=True),
        sa.Column("tokens", JSONB(), nullable=True),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "review_id", "execution_number",
            name="uq_review_executions_review_id_execution_number",
        ),
    )

    op.drop_constraint("fk_reviews_parent_review_id_reviews", "reviews", type_="foreignkey")
    op.drop_column("reviews", "parent_review_id")


def downgrade() -> None:
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
    op.drop_table("review_executions")
