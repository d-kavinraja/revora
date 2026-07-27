"""Add NVIDIA NIM to provider registry.

Revision ID: add_nvidia_provider
Revises: fd45e477b914
Create Date: 2026-07-27 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import uuid


# revision identifiers, used by Alembic.
revision = 'add_nvidia_provider'
down_revision = 'fd45e477b914'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Insert NVIDIA into provider_registry if it doesn't exist
    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO provider_registry
            (id, name, display_name, slug, litellm_provider, api_key_prefix,
             api_key_min_length, base_url_template, default_model, priority,
             supports_streaming, supports_vision, supports_function_calling,
             supports_reasoning, is_enabled, extra_config)
            SELECT
                :id, 'nvidia', 'NVIDIA NIM', 'nvidia', 'nvidia_nim', 'nvapi-',
                15, 'https://integrate.api.nvidia.com/v1', 'nvidia/nemotron-3-ultra-550b-a55b', 10,
                true, true, true, true, true, '{}'
            WHERE NOT EXISTS (
                SELECT 1 FROM provider_registry WHERE slug = 'nvidia' OR name = 'nvidia'
            );
            """
        ),
        {"id": str(uuid.uuid4())}
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM provider_registry WHERE slug = 'nvidia'")
    )
