"""Add settings column to users table.

Revision ID: us3r_s3tt1ngs
Revises: h34lth_f4ll0v3r
Create Date: 2026-07-16 15:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "us3r_s3tt1ngs"
down_revision = "h34lth_f4ll0v3r"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("users")]
    if "settings" not in columns:
        json_type = sa.JSON().with_variant(JSONB, "postgresql")
        op.add_column("users", sa.Column("settings", json_type, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("users")]
    if "settings" in columns:
        op.drop_column("users", "settings")
