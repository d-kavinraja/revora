"""Increase announcement kind column length and correct stale default.

Revision ID: ann_kind_len50
Revises: instauth01
Create Date: 2026-11-12 12:00:00.000000

The announcement kind vocabulary includes ``scheduled_maintenance`` (21
characters), but the column was created as ``VARCHAR(20)``. The API accepts
the value, then PostgreSQL rejects the insert/update with
``StringDataRightTruncationError`` and the request becomes HTTP 500.

This migration widens the column to ``VARCHAR(50)`` and changes the server
default from the invalid ``info`` value to ``general``. Existing rows are
preserved unchanged; downgrade refuses to shrink the column when any stored
kind is longer than 20 characters.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ann_kind_len50"
down_revision: str | None = "instauth01"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_OLD_LENGTH = 20
_NEW_LENGTH = 50


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    if _is_sqlite():
        with op.batch_alter_table("announcements") as batch_op:
            batch_op.alter_column(
                "kind",
                existing_type=sa.String(_OLD_LENGTH),
                type_=sa.String(_NEW_LENGTH),
                existing_nullable=False,
                server_default="general",
            )
    else:
        op.alter_column(
            "announcements",
            "kind",
            existing_type=sa.String(_OLD_LENGTH),
            type_=sa.String(_NEW_LENGTH),
            existing_nullable=False,
            server_default="general",
        )


def downgrade() -> None:
    bind = op.get_bind()
    max_length = bind.execute(
        sa.text("SELECT COALESCE(MAX(LENGTH(kind)), 0) FROM announcements")
    ).scalar()
    if max_length and int(max_length) > _OLD_LENGTH:
        raise RuntimeError(
            "Cannot downgrade announcements.kind to VARCHAR(20): "
            f"stored kind value has length {max_length}."
        )

    if _is_sqlite():
        with op.batch_alter_table("announcements") as batch_op:
            batch_op.alter_column(
                "kind",
                existing_type=sa.String(_NEW_LENGTH),
                type_=sa.String(_OLD_LENGTH),
                existing_nullable=False,
                server_default="info",
            )
    else:
        op.alter_column(
            "announcements",
            "kind",
            existing_type=sa.String(_NEW_LENGTH),
            type_=sa.String(_OLD_LENGTH),
            existing_nullable=False,
            server_default="info",
        )
