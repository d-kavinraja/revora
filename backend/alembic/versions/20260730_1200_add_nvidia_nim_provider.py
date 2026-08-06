"""add_nvidia_nim_provider

Revision ID: 202607301200
Revises: fd45e477b914
Create Date: 2026-07-30 12:00:00.000000

"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '202607301200'
down_revision: str | None = 'fd45e477b914'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Insert NVIDIA NIM into provider_registry
    op.get_bind().execute(
        sa.text(
            """INSERT INTO provider_registry
               (id, name, display_name, slug, litellm_provider, api_key_prefix,
                api_key_min_length, default_model, priority,
                supports_streaming, supports_vision, supports_function_calling,
                supports_reasoning, is_enabled, extra_config)
               VALUES (:id, :name, :display_name, :slug, :litellm_provider, :api_key_prefix,
                       :api_key_min_length, :default_model, :priority,
                       :supports_streaming, :supports_vision, :supports_function_calling,
                       :supports_reasoning, true, '{}')"""
        ),
        {
            "id": str(uuid.uuid4()),
            "name": "nvidia",
            "display_name": "NVIDIA NIM",
            "slug": "nvidia",
            "litellm_provider": "nvidia_nim",
            "api_key_prefix": "nvapi-",
            "api_key_min_length": 50,
            "default_model": "meta/llama-3.1-70b-instruct",
            "priority": 10,
            "supports_streaming": True,
            "supports_vision": True,
            "supports_function_calling": True,
            "supports_reasoning": False,
        },
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM provider_registry WHERE slug = 'nvidia'")
    )
