"""add botaniq_inference_runs

Revision ID: 1799b50a5aa5
Revises: adm1n_s33d
Create Date: 2026-11-01 20:37:14.459905

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '1799b50a5aa5'
down_revision: Union[str, None] = 'adm1n_s33d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('botaniq_inference_runs',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('image_filename', sa.String(length=255), nullable=False),
    sa.Column('image_size_bytes', sa.Integer(), nullable=True),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('test_image_id', sa.String(length=128), nullable=True),
    sa.Column('prediction', sa.Text(), nullable=True),
    sa.Column('predicted_class', sa.String(length=255), nullable=True),
    sa.Column('plant_name', sa.String(length=255), nullable=True),
    sa.Column('plant_type', sa.String(length=32), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('top_5_predictions', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('inference_time_ms', sa.Integer(), nullable=True),
    sa.Column('model_version', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('raw_response', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_botaniq_inference_runs_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_botaniq_inference_runs'))
    )
    op.create_index(op.f('ix_botaniq_inference_runs_user_id'), 'botaniq_inference_runs', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_botaniq_inference_runs_user_id'), table_name='botaniq_inference_runs')
    op.drop_table('botaniq_inference_runs')
