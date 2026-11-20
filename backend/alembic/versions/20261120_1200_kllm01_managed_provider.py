"""Add the managed local kLLM provider (disabled by default).

Revision ID: kllm01_managed
Revises: exeid01
Create Date: 2026-11-20 12:00:00.000000

Additive-only migration:

* ``provider_registry.is_managed`` (server default false) marks server-owned
  providers that never accept user API keys.
* seeds the ``kllm`` provider row with ``is_managed=true``,
  ``is_enabled=false`` and ``status='disabled'``. Enabling therefore needs an
  explicit admin action *and* ``KLLM_ENABLED=true`` in the backend
  environment — there is no half-enabled state.
* seeds a curated ``discovered_models`` catalogue as an offline fallback.
  Live kLLM state always wins; nothing here is served as live telemetry.

``alembic downgrade -1`` removes the seeded rows and the column.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "kllm01_managed"
down_revision: str | None = "exeid01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = sa.JSON().with_variant(postgresql.JSONB, "postgresql")

#: Curated chat models from kLLM's ``models.yaml``. Only used to populate the
#: offline fallback catalogue; the dashboard and repository selector read live
#: kLLM state whenever the relay is reachable.
CURATED_MODELS = (
    # key, display name, context window, vision
    ("qwen3.8-27b", "Qwen3.8 27B", 131072, False),
    ("qwen3.8-27b-256k", "Qwen3.8 27B (256K)", 262144, False),
    ("qwen3.8-27b-vision", "Qwen3.8 27B Vision", 131072, True),
    ("qwen3.8-27b-abliterated", "Qwen3.8 27B Abliterated", 131072, True),
    ("qwen3.8-27b-abliterated-256k", "Qwen3.8 27B Abliterated (256K)", 262144, False),
    (
        "qwen3.8-27b-vision-abliterated-256k",
        "Qwen3.8 27B Vision Abliterated (256K)",
        262144,
        True,
    ),
    ("qwen3.8-27b-mtp", "Qwen3.8 27B MTP", 131072, False),
    ("nanbeige4.3-33b", "Nanbeige4.3 33B", 32768, False),
    ("nanbeige4.3-33b-uncensored", "Nanbeige4.3 33B Uncensored", 65536, False),
    ("nanbeige4.3-33b-128k", "Nanbeige4.3 33B (128K)", 131072, False),
    ("qwen3.6-35b", "Qwen3.6 35B A3B", 262144, False),
    ("qwen3.6-35b-abliterated", "Qwen3.6 35B A3B Abliterated", 262144, False),
    ("qwen3-coder-30b-abliterated", "Qwen3 Coder 30B Abliterated", 98304, False),
    ("qwen3-30b-a3b-abliterated", "Qwen3 30B A3B Abliterated", 32768, False),
    ("coder-32b-abliterated", "Qwen2.5 Coder 32B Abliterated", 32768, False),
    ("qwen3-32b-abliterated", "Qwen3 32B Abliterated", 32768, False),
    ("qwq-32b-abliterated", "QwQ 32B Abliterated", 32768, False),
    ("r1-distill-32b-abliterated", "R1 Distill 32B Abliterated", 32768, False),
    ("gpt-oss-20b-abliterated", "GPT-OSS 20B Abliterated", 131072, False),
    ("validate-3b", "Validate 3B (pipeline test)", 8192, False),
)


def upgrade() -> None:
    op.add_column(
        "provider_registry",
        sa.Column(
            "is_managed", sa.Boolean(), server_default="false", nullable=False
        ),
    )

    conn = op.get_bind()
    existing = conn.execute(
        sa.text("SELECT id FROM provider_registry WHERE slug = 'kllm'")
    ).first()
    if existing is None:
        conn.execute(
            sa.text(
                """INSERT INTO provider_registry
                   (id, name, display_name, slug, litellm_provider,
                    api_key_prefix, api_key_min_length, base_url_template,
                    default_model, timeout_seconds, max_retries, priority,
                    supports_streaming, supports_vision,
                    supports_function_calling, supports_reasoning,
                    is_enabled, status, allow_key_addition, is_managed,
                    extra_config)
                   VALUES
                   (:id, 'kllm', 'kLLM', 'kllm', 'openai',
                    NULL, 0, NULL,
                    'qwen3.8-27b', 300, 1, 10,
                    true, true, true, true,
                    false, 'disabled', false, true,
                    '{}')"""
            ),
            {"id": _uuid()},
        )

    discovered = sa.table(
        "discovered_models",
        sa.column("id", sa.Uuid(as_uuid=True)),
        sa.column("provider_slug", sa.String(50)),
        sa.column("model_id", sa.String(200)),
        sa.column("display_name", sa.String(200)),
        sa.column("context_window", sa.Integer()),
        sa.column("is_free", sa.Boolean()),
        sa.column("description", sa.String()),
        sa.column("raw_metadata", JSONB),
        sa.column("last_synced_at", sa.DateTime(timezone=True)),
    )

    known = {
        row[0]
        for row in conn.execute(
            sa.text(
                "SELECT model_id FROM discovered_models WHERE provider_slug = 'kllm'"
            )
        )
    }
    now = datetime.now(UTC)
    rows = [
        {
            "id": _uuid(),
            "provider_slug": "kllm",
            "model_id": key,
            "display_name": display,
            "context_window": context,
            "is_free": True,
            "description": "Curated kLLM catalogue entry (live state is authoritative).",
            "raw_metadata": {"vision": vision, "source": "curated"},
            "last_synced_at": now,
        }
        for key, display, context, vision in CURATED_MODELS
        if key not in known
    ]
    if rows:
        op.bulk_insert(discovered, rows)


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM discovered_models WHERE provider_slug = 'kllm'")
    )
    conn.execute(sa.text("DELETE FROM provider_registry WHERE slug = 'kllm'"))
    op.drop_column("provider_registry", "is_managed")


def _uuid() -> str:
    return str(uuid.uuid4())
