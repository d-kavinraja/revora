"""Add ollama_cloud provider

Revision ID: a1b2c3d4e5f6
Revises: 7e952e316dce
Create Date: 2026-08-11 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '7e952e316dce'
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
            'ollama_cloud', 'Ollama Cloud', 'ollama_cloud', 'ollama',
            NULL, 15, 'https://ollama.com', 'qwen3:32b',
            300, 3, 6,
            true, false, false, false,
            true, '{}'
        )
        ON CONFLICT (slug) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM provider_registry WHERE slug = 'ollama_cloud'")
