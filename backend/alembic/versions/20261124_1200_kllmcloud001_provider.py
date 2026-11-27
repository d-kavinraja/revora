"""Add the independent kLLM Cloud provider and per-surface model gates.

Revision ID: kllmcloud001
Revises: chatpersist001
Create Date: 2026-11-24 12:00:00.000000

Additive-only migration:

* seeds the ``kllm-cloud`` provider row (``is_managed=true``,
  ``is_enabled=false``, ``status='disabled'``). Enabling needs an explicit
  admin action *and* ``KLLM_CLOUD_ENABLED=true`` in the backend environment, so
  there is no half-enabled state.
* ``extra_config`` records the approval policy: newly discovered canonical
  models stay pending approval (``approval_required=true``,
  ``auto_approve=false``).
* adds ``model_overrides.chat_enabled`` / ``review_enabled`` - per-surface
  availability, both defaulting to true so every existing provider keeps its
  current behaviour.

No catalogue rows are seeded: kLLM Cloud models are discovered from the relay
``GET /v1/models`` and never fabricated offline.

``alembic downgrade -1`` removes the seeded row and both columns.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'kllmcloud001'
down_revision: str | None = 'chatpersist001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROVIDER_SLUG = 'kllm-cloud'


def upgrade() -> None:
    op.add_column(
        'model_overrides',
        sa.Column('chat_enabled', sa.Boolean(), server_default='true', nullable=False),
    )
    op.add_column(
        'model_overrides',
        sa.Column('review_enabled', sa.Boolean(), server_default='true', nullable=False),
    )

    conn = op.get_bind()
    existing = conn.execute(
        sa.text('SELECT id FROM provider_registry WHERE slug = :slug'),
        {'slug': PROVIDER_SLUG},
    ).first()
    if existing is None:
        conn.execute(
            sa.text(
                'INSERT INTO provider_registry '
                '(id, name, display_name, slug, litellm_provider, api_key_prefix, '
                'api_key_min_length, base_url_template, default_model, '
                'timeout_seconds, max_retries, priority, supports_streaming, '
                'supports_vision, supports_function_calling, supports_reasoning, '
                'is_enabled, status, allow_key_addition, is_managed, extra_config) '
                'VALUES (:id, :slug, :display, :slug, :litellm, NULL, 0, NULL, '
                ':default_model, 300, 1, 20, true, true, true, true, false, '
                '\'disabled\', false, true, :extra_config)'
            ),
            {
                'id': str(uuid.uuid4()),
                'slug': PROVIDER_SLUG,
                'display': 'kLLM Cloud',
                'litellm': 'openai',
                'default_model': 'qwen3.8-27b',
                'extra_config': '{"approval_required": true, "auto_approve": false}',
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text('DELETE FROM provider_registry WHERE slug = :slug'),
        {'slug': PROVIDER_SLUG},
    )
    op.drop_column('model_overrides', 'review_enabled')
    op.drop_column('model_overrides', 'chat_enabled')
