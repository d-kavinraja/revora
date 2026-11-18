"""add execution_id to verification_results

Revision ID: exeid01
Revises: verifyttl01
Create Date: 2026-11-18 00:00:00.000000

Adds a nullable execution_id foreign key to verification_results so findings
are attributed to the ReviewExecution that produced them. Nullable and
non-destructive:

- Existing rows keep NULL execution_id and stay readable. Historical findings
  are never rewritten with guessed execution ids.
- Column / constraint / index creation is guarded with inspector checks so the
  migration is idempotent and safe to run against a disposable local database.
- ondelete=SET NULL mirrors the model: deleting an execution never deletes the
  findings attributed to it.
- Batch mode is used for SQLite compatibility (SQLite cannot ALTER an existing
  table to add a constraint); on PostgreSQL it emits plain ALTER statements.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "exeid01"
down_revision: Union[str, None] = "verifyttl01"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    columns = {col["name"] for col in insp.get_columns("verification_results")}
    indexes = {idx["name"] for idx in insp.get_indexes("verification_results")}

    if "execution_id" in columns and "ix_verification_results_execution_id" in indexes:
        return

    with op.batch_alter_table("verification_results") as batch_op:
        if "execution_id" not in columns:
            batch_op.add_column(
                sa.Column(
                    "execution_id",
                    sa.Uuid(),
                    sa.ForeignKey(
                        "review_executions.id",
                        name="fk_verification_results_execution_id_review_executions",
                        ondelete="SET NULL",
                    ),
                    nullable=True,
                )
            )
        if "ix_verification_results_execution_id" not in indexes:
            batch_op.create_index(
                "ix_verification_results_execution_id",
                ["execution_id"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    columns = {col["name"] for col in insp.get_columns("verification_results")}
    indexes = {idx["name"] for idx in insp.get_indexes("verification_results")}

    with op.batch_alter_table("verification_results") as batch_op:
        if "ix_verification_results_execution_id" in indexes:
            batch_op.drop_index("ix_verification_results_execution_id")
        if "execution_id" in columns:
            batch_op.drop_column("execution_id")
