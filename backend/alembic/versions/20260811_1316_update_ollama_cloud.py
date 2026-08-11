"""Update ollama_cloud to use openai compatible endpoint

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-11 13:16:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6g7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE provider_registry
        SET litellm_provider = 'openai',
            base_url_template = 'https://ollama.com/v1'
        WHERE slug = 'ollama_cloud';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE provider_registry
        SET litellm_provider = 'ollama',
            base_url_template = 'https://ollama.com'
        WHERE slug = 'ollama_cloud';
        """
    )
