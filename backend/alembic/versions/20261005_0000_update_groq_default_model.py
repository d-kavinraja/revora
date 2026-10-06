"""Update groq default model (llama-3.3 deprecated by Groq 2026-08-16)

Revision ID: d5g6r7o8q9v1
Revises: c4h5r6e7p8v9
Create Date: 2026-10-05 00:00:00.000000

Groq shut down `llama-3.3-70b-versatile` (and `llama-3.1-8b-instant`) for
free and developer-tier usage on 2026-08-16, recommending
`openai/gpt-oss-120b` as the replacement flagship. This data-only
migration points the seeded Groq registry row at the current production
flagship and marks reasoning support (GPT-OSS models are reasoning
models). See https://console.groq.com/docs/deprecations.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5g6r7o8q9v1'
down_revision: Union[str, None] = 'c4h5r6e7p8v9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE provider_registry
        SET default_model = 'openai/gpt-oss-120b',
            supports_reasoning = true,
            updated_at = NOW()
        WHERE slug = 'groq';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE provider_registry
        SET default_model = 'llama-3.3-70b-versatile',
            supports_reasoning = false,
            updated_at = NOW()
        WHERE slug = 'groq';
        """
    )
