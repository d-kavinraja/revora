"""add_sync_recovery

Revision ID: 20260801_0900
Revises: 20260731_1200
Create Date: 2026-08-01

Automatic recovery & repository synchronization after server downtime:

- repositories.removed_at   — explicit "Removed/Uninstalled" marker (history is
  preserved; the row is never deleted once reviews exist).
- repositories.is_archived  — GitHub archived flag surfaced during sync.
- installations.permissions_ok — required GitHub App permissions present
  (used to gate review enqueueing and surface "Permission Required").
- installations.last_sync_* — per-installation sync status for the UI
  ("Last synchronized 2 minutes ago").
- sync_runs — audit trail for every sync pass (startup / background /
  manual / webhook / recovery) with reason, status and per-repo counts.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "20260801_0900"
down_revision = "20260731_1200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "repositories",
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "repositories",
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.add_column(
        "installations",
        sa.Column("permissions_ok", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "installations",
        sa.Column("last_sync_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "installations",
        sa.Column("last_sync_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "installations",
        sa.Column("last_sync_status", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "installations",
        sa.Column("last_sync_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "installations",
        sa.Column("last_sync_reason", sa.String(length=20), nullable=True),
    )

    op.create_table(
        "sync_runs",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("reason", sa.String(length=20), nullable=False),
        sa.Column(
            "triggered_by",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("repo_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repos_added", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repos_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repos_removed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repos_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prs_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prs_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("jobs_enqueued", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("details", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_sync_runs_started_at", "sync_runs", ["started_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_sync_runs_started_at", table_name="sync_runs")
    op.drop_table("sync_runs")

    op.drop_column("installations", "last_sync_reason")
    op.drop_column("installations", "last_sync_error")
    op.drop_column("installations", "last_sync_status")
    op.drop_column("installations", "last_sync_completed_at")
    op.drop_column("installations", "last_sync_started_at")
    op.drop_column("installations", "permissions_ok")

    op.drop_column("repositories", "is_archived")
    op.drop_column("repositories", "removed_at")
