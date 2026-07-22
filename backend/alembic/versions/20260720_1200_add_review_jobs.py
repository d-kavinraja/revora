"""add review_jobs table

Revision ID: 001_review_jobs
Create Date: 2026-07-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001_review_jobs"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create job_status enum type
    job_status = postgresql.ENUM(
        "queued", "running", "completed", "failed", "cancelled",
        name="job_status",
        create_type=False,
    )
    job_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "review_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("repo_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("repositories.id"), nullable=True),
        sa.Column("pr_number", sa.Integer(), nullable=False),
        sa.Column("head_sha", sa.String(40), nullable=False),
        sa.Column("base_sha", sa.String(40), nullable=True),
        sa.Column("delivery_id", sa.String(100), nullable=False, index=True),
        sa.Column("status", postgresql.ENUM(name="job_status", create_type=False), nullable=False, server_default="queued", index=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("worker_id", sa.String(100), nullable=True),
        sa.UniqueConstraint("delivery_id", "head_sha", name="uq_review_job_delivery_sha"),
    )

    # Indexes for worker polling and lookups
    op.create_index("ix_review_jobs_status_created", "review_jobs", ["status", "created_at"])
    op.create_index("ix_review_jobs_repo_pr", "review_jobs", ["repo_id", "pr_number"])


def downgrade() -> None:
    op.drop_table("review_jobs")
    op.execute("DROP TYPE IF EXISTS job_status")
