"""merge remove azure openai and botaniq inference runs

Revision ID: c77fb53c4efc
Revises: rem0v3_4zur3, 1799b50a5aa5
Create Date: 2026-11-02 11:47:07.160191

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c77fb53c4efc'
down_revision: Union[str, None] = ('rem0v3_4zur3', '1799b50a5aa5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
