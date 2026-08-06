"""immutable_execution_metadata

Revision ID: 7798fbb499b6
Revises: 8493bf6f645e
Create Date: 2026-08-06 16:47:50.102544

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7798fbb499b6'
down_revision: Union[str, None] = '8493bf6f645e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add columns to review_executions
    op.add_column("review_executions", sa.Column("summary", sa.String(), nullable=True))
    op.add_column("review_executions", sa.Column("stats", sa.JSON(), nullable=True, server_default="{}"))
    op.add_column("review_executions", sa.Column("error_message", sa.String(), nullable=True))
    op.add_column("review_executions", sa.Column("prompt_version", sa.String(50), nullable=True))
    op.add_column("review_executions", sa.Column("configuration_snapshot", sa.JSON(), nullable=True, server_default="{}"))
    op.add_column("review_executions", sa.Column("api_key_id", sa.UUID(as_uuid=True), nullable=True))
    op.add_column("review_executions", sa.Column("repository_full_name", sa.String(500), nullable=True))
    op.add_column("review_executions", sa.Column("base_branch", sa.String(255), nullable=True))
    op.add_column("review_executions", sa.Column("head_branch", sa.String(255), nullable=True))
    op.add_column("review_executions", sa.Column("pr_number", sa.Integer(), nullable=True))

    # Drop tables/columns
    op.drop_table("review_execution_contexts")
    op.drop_column("reviews", "summary")
    op.drop_column("reviews", "stats")
    op.drop_column("reviews", "error_message")


def downgrade() -> None:
    pass

