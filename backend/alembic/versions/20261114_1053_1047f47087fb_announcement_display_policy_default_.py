"""announcement_display_policy_default_every_login

Revision ID: 1047f47087fb
Revises: ann_display_pol
Create Date: 2026-11-14 10:53:23.180476

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1047f47087fb'
down_revision: Union[str, None] = 'ann_display_pol'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("announcements") as batch_op:
        batch_op.alter_column(
            "display_policy",
            server_default="every_login",
        )


def downgrade() -> None:
    with op.batch_alter_table("announcements") as batch_op:
        batch_op.alter_column(
            "display_policy",
            server_default="once_until_dismissed",
        )
