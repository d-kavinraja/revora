"""Add users.token_version for session revocation.

Revision ID: s3c8t0k3nv1r
Revises: m0u7t9h1m2a3p
Create Date: 2026-10-13 12:00:00.000000

JWTs carry a `tv` claim compared against this column. Bumping the column
invalidates every previously issued token (logout / forced rotation).
server_default=0 keeps pre-existing tokens valid until natural expiry.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "s3c8t0k3nv1r"
down_revision: Union[str, None] = "m0u7t9h1m2a3p"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
