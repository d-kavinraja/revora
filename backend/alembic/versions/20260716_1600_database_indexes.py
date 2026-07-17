"""Add database indexes for performance.

Revision ID: d4t4_1nd3x3s
Revises: us3r_s3tt1ngs
Create Date: 2026-07-16 16:00:00.000000
"""
from alembic import op

revision = "d4t4_1nd3x3s"
down_revision = "us3r_s3tt1ngs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Indexes for llm_token_usage
    op.create_index("ix_token_usage_user_created", "llm_token_usage", ["user_id", "created_at"])
    op.create_index("ix_token_usage_provider_model", "llm_token_usage", ["provider", "model"])

    # Indexes for provider_health
    op.create_index("ix_provider_health_status", "provider_health", ["status"])

    # Indexes for failover_log
    op.create_index("ix_failover_log_created", "failover_log", ["created_at"])

    # Indexes for llm_request_log
    op.create_index("ix_llm_request_log_created", "llm_request_log", ["created_at"])
    op.create_index("ix_llm_request_log_provider_status", "llm_request_log", ["provider", "status"])

    # Indexes for cost_budgets
    op.create_index("ix_cost_budgets_user_active", "cost_budgets", ["user_id", "is_active"])


def downgrade() -> None:
    op.drop_index("ix_cost_budgets_user_active", table_name="cost_budgets")
    op.drop_index("ix_llm_request_log_provider_status", table_name="llm_request_log")
    op.drop_index("ix_llm_request_log_created", table_name="llm_request_log")
    op.drop_index("ix_failover_log_created", table_name="failover_log")
    op.drop_index("ix_provider_health_status", table_name="provider_health")
    op.drop_index("ix_token_usage_provider_model", table_name="llm_token_usage")
    op.drop_index("ix_token_usage_user_created", table_name="llm_token_usage")
