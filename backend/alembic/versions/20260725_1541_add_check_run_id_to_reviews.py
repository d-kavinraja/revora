"""add github_check_run_id to reviews

Revision ID: add_check_run_id_001
Revises: 91801a79cc5b
Create Date: 2026-07-25 15:41:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'add_check_run_id_001'
down_revision: str | None = '91801a79cc5b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add github_check_run_id to reviews table so we can close the check run on cancellation
    op.add_column(
        'reviews',
        sa.Column('github_check_run_id', sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('reviews', 'github_check_run_id')
