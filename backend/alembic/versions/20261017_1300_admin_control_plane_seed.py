"""Seed feature flags with status='enabled' (no behavior change at deploy).

Revision ID: adm1n_s33d
Revises: adm1n_sch3ma
Create Date: 2026-10-17 13:00:00.000000

Every §11 flag key is inserted as `enabled`, matching the pre-flag behavior
of the application. Code treats a missing row as `enabled` too (the SQLite
`create_all` dev path never runs this migration).
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "adm1n_s33d"
down_revision: str | None = "adm1n_sch3ma"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FLAG_KEYS = (
    "model_lab",
    "mouthmap",
    "api_keys_add",
    "routing_mapping",
    "review_initiation",
    "usage",
    "analytics",
    "guide",
)


def upgrade() -> None:
    feature_flags = sa.table(
        "feature_flags",
        sa.column("id", sa.Uuid(as_uuid=True)),
        sa.column("key", sa.String(100)),
        sa.column("status", sa.String(20)),
    )
    conn = op.get_bind()
    existing = {
        row[0] for row in conn.execute(sa.text("SELECT key FROM feature_flags"))
    }
    rows = [
        {"id": uuid.uuid4(), "key": key, "status": "enabled"}
        for key in FLAG_KEYS
        if key not in existing
    ]
    if rows:
        op.bulk_insert(feature_flags, rows)


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM feature_flags WHERE key IN :keys").bindparams(
            sa.bindparam("keys", expanding=True)
        ),
        {"keys": list(FLAG_KEYS)},
    )
