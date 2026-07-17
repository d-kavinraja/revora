"""Provider registry and API key health tables.

Revision ID: pr0v1d3r_r3g1stry
Revises: pr0mpt_bu1ld3r
Create Date: 2026-07-16 11:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "pr0v1d3r_r3g1stry"
down_revision = "pr0mpt_bu1ld3r"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # JSON type variant for SQLite/PostgreSQL compatibility
    json_type = sa.JSON().with_variant(JSONB, "postgresql")

    # provider_registry table
    op.create_table(
        "provider_registry",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(50), unique=True, nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("slug", sa.String(50), unique=True, nullable=False),
        sa.Column("litellm_provider", sa.String(50), nullable=False),
        sa.Column("api_key_prefix", sa.String(10), nullable=True),
        sa.Column("api_key_min_length", sa.Integer(), server_default="15"),
        sa.Column("base_url_template", sa.String(500), nullable=True),
        sa.Column("default_model", sa.String(100), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), server_default="60"),
        sa.Column("max_retries", sa.Integer(), server_default="3"),
        sa.Column("priority", sa.Integer(), server_default="0"),
        sa.Column("supports_streaming", sa.Boolean(), server_default="true"),
        sa.Column("supports_vision", sa.Boolean(), server_default="false"),
        sa.Column("supports_function_calling", sa.Boolean(), server_default="false"),
        sa.Column("supports_reasoning", sa.Boolean(), server_default="false"),
        sa.Column("is_enabled", sa.Boolean(), server_default="true"),
        sa.Column("extra_config", json_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # api_key_health table
    op.create_table(
        "api_key_health",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "key_id",
            sa.Uuid(),
            sa.ForeignKey("api_keys.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_type", sa.String(50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_api_key_health_key_id", "api_key_health", ["key_id"])

    # Seed 10 providers
    providers = [
        {
            "name": "openai", "display_name": "OpenAI", "slug": "openai",
            "litellm_provider": "openai", "api_key_prefix": "sk-",
            "default_model": "gpt-4o", "priority": 1,
            "supports_streaming": True, "supports_vision": True,
            "supports_function_calling": True, "supports_reasoning": True,
        },
        {
            "name": "anthropic", "display_name": "Claude", "slug": "anthropic",
            "litellm_provider": "anthropic", "api_key_prefix": "sk-ant-",
            "default_model": "claude-sonnet-4-20250514", "priority": 2,
            "supports_streaming": True, "supports_vision": True,
            "supports_function_calling": True, "supports_reasoning": True,
        },
        {
            "name": "gemini", "display_name": "Google Gemini", "slug": "gemini",
            "litellm_provider": "gemini", "api_key_prefix": "AI",
            "default_model": "gemini-1.5-flash", "priority": 0,
            "supports_streaming": True, "supports_vision": True,
            "supports_function_calling": True, "supports_reasoning": True,
        },
        {
            "name": "groq", "display_name": "Groq", "slug": "groq",
            "litellm_provider": "groq", "api_key_prefix": "gsk_",
            "default_model": "llama-3.3-70b-versatile", "priority": 4,
            "supports_streaming": True, "supports_vision": False,
            "supports_function_calling": True, "supports_reasoning": False,
        },
        {
            "name": "deepseek", "display_name": "DeepSeek", "slug": "deepseek",
            "litellm_provider": "deepseek", "api_key_prefix": "sk-",
            "default_model": "deepseek-chat", "priority": 3,
            "supports_streaming": True, "supports_vision": False,
            "supports_function_calling": True, "supports_reasoning": True,
        },
        {
            "name": "openrouter", "display_name": "OpenRouter", "slug": "openrouter",
            "litellm_provider": "openrouter", "api_key_prefix": "sk-or-",
            "default_model": "anthropic/claude-3.5-sonnet", "priority": 5,
            "supports_streaming": True, "supports_vision": True,
            "supports_function_calling": True, "supports_reasoning": False,
        },
        {
            "name": "azure_openai", "display_name": "Azure OpenAI", "slug": "azure_openai",
            "litellm_provider": "azure", "api_key_prefix": None,
            "default_model": "gpt-4o", "priority": 6,
            "supports_streaming": True, "supports_vision": True,
            "supports_function_calling": True, "supports_reasoning": True,
        },
        {
            "name": "ollama", "display_name": "Ollama", "slug": "ollama",
            "litellm_provider": "ollama", "api_key_prefix": None,
            "api_key_min_length": 0,
            "default_model": "llama3.1", "priority": 7,
            "supports_streaming": True, "supports_vision": False,
            "supports_function_calling": False, "supports_reasoning": False,
        },
        {
            "name": "cohere", "display_name": "Cohere", "slug": "cohere",
            "litellm_provider": "cohere", "api_key_prefix": None,
            "default_model": "command-r-plus", "priority": 8,
            "supports_streaming": True, "supports_vision": False,
            "supports_function_calling": True, "supports_reasoning": False,
        },
        {
            "name": "mistral", "display_name": "Mistral AI", "slug": "mistral",
            "litellm_provider": "mistral", "api_key_prefix": None,
            "default_model": "mistral-large-latest", "priority": 9,
            "supports_streaming": True, "supports_vision": False,
            "supports_function_calling": True, "supports_reasoning": False,
        },
    ]

    import uuid
    for p in providers:
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
                "name": p["name"],
                "display_name": p["display_name"],
                "slug": p["slug"],
                "litellm_provider": p["litellm_provider"],
                "api_key_prefix": p.get("api_key_prefix"),
                "api_key_min_length": p.get("api_key_min_length", 15),
                "default_model": p["default_model"],
                "priority": p["priority"],
                "supports_streaming": p["supports_streaming"],
                "supports_vision": p["supports_vision"],
                "supports_function_calling": p["supports_function_calling"],
                "supports_reasoning": p["supports_reasoning"],
            },
        )


def downgrade() -> None:
    op.drop_index("ix_api_key_health_key_id", table_name="api_key_health")
    op.drop_table("api_key_health")
    op.drop_table("provider_registry")
