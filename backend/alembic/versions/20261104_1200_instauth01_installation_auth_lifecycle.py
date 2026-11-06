"""add installation auth lifecycle fields

Revision ID: instauth01
Revises: op3r4t10ns01
Create Date: 2026-11-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "instauth01"
down_revision: Union[str, None] = "op3r4t10ns01"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "installations",
        sa.Column("app_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "installations",
        sa.Column(
            "lifecycle_status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column(
        "installations",
        sa.Column("last_auth_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "installations",
        sa.Column("last_auth_success_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "installations",
        sa.Column("last_auth_error_category", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "installations",
        sa.Column(
            "auth_failure_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "installations",
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute(
        "UPDATE installations SET lifecycle_status = 'suspended' "
        "WHERE suspended_at IS NOT NULL"
    )
    op.execute(
        "UPDATE installations SET lifecycle_status = 'reauthorization_required' "
        "WHERE suspended_at IS NULL AND permissions_ok = false"
    )
    op.create_index(
        "ix_installations_lifecycle_retry",
        "installations",
        ["lifecycle_status", "retry_after"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_installations_lifecycle_retry", table_name="installations")
    op.drop_column("installations", "retry_after")
    op.drop_column("installations", "auth_failure_count")
    op.drop_column("installations", "last_auth_error_category")
    op.drop_column("installations", "last_auth_success_at")
    op.drop_column("installations", "last_auth_checked_at")
    op.drop_column("installations", "lifecycle_status")
    op.drop_column("installations", "app_id")
