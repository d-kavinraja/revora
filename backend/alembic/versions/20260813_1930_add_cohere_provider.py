"""Add cohere provider

Revision ID: c4h5r6e7p8v9
Revises: b2c3d4e5f6g7
Create Date: 2026-08-13 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4h5r6e7p8v9'
down_revision: Union[str, None] = 'b2c3d4e5f6g7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO provider_registry (
            id, created_at, updated_at, name, display_name, slug, litellm_provider,
            api_key_prefix, api_key_min_length, base_url_template, default_model,
            timeout_seconds, max_retries, priority, supports_streaming, supports_vision,
            supports_function_calling, supports_reasoning, is_enabled, extra_config
        ) VALUES (
            gen_random_uuid(), NOW(), NOW(),
            'cohere', 'Cohere', 'cohere', 'cohere',
            NULL, 15, NULL, 'command-a-03-2025',
            300, 3, 7,
            true, false, true, false,
            true, '{}'
        )
        ON CONFLICT (slug) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM provider_registry WHERE slug = 'cohere'")
