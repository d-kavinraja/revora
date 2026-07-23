"""add verification tables

Revision ID: 20260718_1200
Revises: pr0mpt_bu1ld3r
Create Date: 2026-07-18 12:00:00.000000

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "20260718_1200"
down_revision: Union[str, None] = "d4t4_1nd3x3s"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "verification_results",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "review_id",
            UUID(as_uuid=True),
            sa.ForeignKey("reviews.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        sa.Column("finding_id", sa.String(100), index=True, nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=True),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("suggested_fix", sa.Text(), nullable=True),
        sa.Column("is_verified", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("confidence_score", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
    )

    op.create_table(
        "review_evidence",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "verification_result_id",
            UUID(as_uuid=True),
            sa.ForeignKey("verification_results.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        sa.Column("evidence_type", sa.String(50), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata_json", JSONB, server_default="{}"),
    )

    op.create_table(
        "hallucination_reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "verification_result_id",
            UUID(as_uuid=True),
            sa.ForeignKey("verification_results.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
            unique=True,
        ),
        sa.Column("hallucination_type", sa.String(50), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
    )

    op.create_table(
        "false_positive_reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "verification_result_id",
            UUID(as_uuid=True),
            sa.ForeignKey("verification_results.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
            unique=True,
        ),
        sa.Column("reason_category", sa.String(50), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
    )

    op.create_table(
        "verification_metrics",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "review_id",
            UUID(as_uuid=True),
            sa.ForeignKey("reviews.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        sa.Column("total_findings", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "verified_findings", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "rejected_findings", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "hallucinations_detected", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "false_positives_filtered", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("avg_confidence", sa.Float(), server_default="0.0", nullable=False),
        sa.Column(
            "verification_duration_ms", sa.Integer(), server_default="0", nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("verification_metrics")
    op.drop_table("false_positive_reports")
    op.drop_table("hallucination_reports")
    op.drop_table("review_evidence")
    op.drop_table("verification_results")
