"""Add mouthmap_inference_runs table for Model Lab history.

Revision ID: m0u7t9h1m2a3p
Revises: d5g6r7o8q9v1
Create Date: 2026-10-08 12:00:00.000000

Inference-only persistence for the MouthMap Model Lab.
Stores real completed/failed runs owned by the requesting user.
No training data, no mock data.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "m0u7t9h1m2a3p"
down_revision: Union[str, None] = "d5g6r7o8q9v1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mouthmap_inference_runs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("video_filename", sa.String(255), nullable=False),
        sa.Column("video_size_bytes", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False, server_default="upload"),
        sa.Column("test_video_id", sa.String(128), nullable=True),
        sa.Column("prediction", sa.Text(), nullable=True),
        sa.Column("expected", sa.Text(), nullable=True),
        sa.Column("is_match", sa.Boolean(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("inference_time_ms", sa.Integer(), nullable=True),
        sa.Column("frames_processed", sa.Integer(), nullable=True),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="completed"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "raw_response",
            sa.JSON().with_variant(postgresql.JSONB, "postgresql"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_mouthmap_inference_runs_user_id",
        "mouthmap_inference_runs",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mouthmap_inference_runs_user_id", table_name="mouthmap_inference_runs"
    )
    op.drop_table("mouthmap_inference_runs")
