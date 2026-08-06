"""add_updated_at_to_audit_logs

Revision ID: 20260730_1600
Revises: 20260730_1500
Create Date: 2026-07-30

Adds missing updated_at column to audit_logs table.
The AuditLog model inherits updated_at from Base but the
original migration (20260730_1300) omitted the column.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260730_1600"
down_revision = "20260730_1500"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_logs",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("audit_logs", "updated_at")
