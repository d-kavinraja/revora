"""add title column to verification_results

Revision ID: verifyttl01
Revises: webhookdlv01
Create Date: 2026-11-15 00:00:00.000000

The VerificationResultModel has always mapped a `title` column, but no
migration ever created it, so production inserts that set it fail with
"column title of relation verification_results does not exist". This adds the
column as nullable and non-destructive, preserving all existing records.

Uses IF NOT EXISTS / IF EXISTS so the migration is idempotent: if the
column was added manually or by a previous partial run, the migration
succeeds without error instead of failing with DuplicateColumnError.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "verifyttl01"
down_revision: Union[str, None] = "webhookdlv01"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE verification_results "
        "ADD COLUMN IF NOT EXISTS title VARCHAR(255)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE verification_results DROP COLUMN IF EXISTS title"
    )
