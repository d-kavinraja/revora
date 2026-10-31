"""Remove the Azure OpenAI provider and its configuration.

Audit logs and historical review/usage records are intentionally preserved.

Revision ID: rem0v3_4zur3
Revises: adm1n_s33d
Create Date: 2026-10-31 12:00:00.000000
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "rem0v3_4zur3"
down_revision: Union[str, None] = "adm1n_s33d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Credentials and their cascading key-health snapshots.
    op.execute("DELETE FROM api_keys WHERE provider IN ('azure_openai', 'azure')")

    # Provider configuration, caches and per-user defaults.
    op.execute(
        "DELETE FROM discovered_models "
        "WHERE provider_slug IN ('azure_openai', 'azure')"
    )
    op.execute(
        "DELETE FROM model_overrides WHERE provider_slug IN ('azure_openai', 'azure')"
    )
    op.execute(
        "DELETE FROM cost_budgets WHERE provider IN ('azure_openai', 'azure')"
    )
    op.execute(
        "DELETE FROM provider_health WHERE provider IN ('azure_openai', 'azure')"
    )
    op.execute(
        "UPDATE users SET default_provider = NULL "
        "WHERE default_provider IN ('azure_openai', 'azure')"
    )

    # The registry row is the source of the Providers page listing.
    op.execute(
        "DELETE FROM provider_registry "
        "WHERE slug IN ('azure_openai', 'azure') "
        "OR name IN ('azure_openai', 'azure') "
        "OR litellm_provider = 'azure'"
    )


def downgrade() -> None:
    op.execute(
        """
        INSERT INTO provider_registry (
            id, created_at, updated_at, name, display_name, slug, litellm_provider,
            api_key_prefix, api_key_min_length, base_url_template, default_model,
            timeout_seconds, max_retries, priority, supports_streaming, supports_vision,
            supports_function_calling, supports_reasoning, is_enabled, extra_config,
            status, status_message, status_expires_at, allow_key_addition
        ) VALUES (
            gen_random_uuid(), NOW(), NOW(),
            'azure_openai', 'Azure OpenAI', 'azure_openai', 'azure',
            NULL, 15, NULL, 'gpt-4o',
            300, 3, 6,
            true, true, true, true, true, '{}',
            'under_testing', NULL, NULL, true
        )
        ON CONFLICT (slug) DO NOTHING;
        """
    )
