"""Add openrouter provider

Revision ID: 7e952e316dce
Revises: f9f8368f2ff3
Create Date: 2026-08-07 20:52:44.755294

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7e952e316dce'
down_revision: Union[str, None] = 'f9f8368f2ff3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO provider_registry (
            id, created_at, updated_at, name, display_name, slug, litellm_provider,
            api_key_prefix, api_key_min_length, default_model, timeout_seconds,
            max_retries, priority, supports_streaming, supports_vision,
            supports_function_calling, supports_reasoning, is_enabled, extra_config
        ) VALUES (
            gen_random_uuid(), NOW(), NOW(), 'OpenRouter', 'OpenRouter', 'openrouter', 'openrouter',
            'sk-or-v1-', 20, 'google/gemma-3-27b-it:free', 300, 3, 5,
            true, false, false, false, true, '{}'
        )
        ON CONFLICT (slug) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM provider_registry WHERE slug = 'openrouter'")
