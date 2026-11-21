"""Add onboarding_completed flag to users.

Revision ID: onbd01_onboarding_completed
Revises: kllm01_managed
Create Date: 2026-11-21 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision: str = "onbd01_onboarding_completed"
down_revision: str | None = "kllm01_managed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "onboarding_completed",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )
    # Backfill established accounts so they are not re-prompted after deploy.
    op.execute(sa.text("UPDATE users SET onboarding_completed = TRUE"))


def downgrade() -> None:
    op.drop_column("users", "onboarding_completed")
