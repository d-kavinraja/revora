"""Announcement display policies, versioning and per-subject state.

Revision ID: ann_display_pol
Revises: ann_kind_len50
Create Date: 2026-11-13 12:00:00.000000

Adds the announcement display-policy machinery:

* ``announcements.version`` — published-content revision. Dismissal state
  is keyed by ``(announcement, version)``, so bumping the version makes an
  updated announcement eligible again for subjects that dismissed the
  previous version.
* ``announcements.display_policy`` — ``once_until_dismissed`` (default),
  ``every_login`` or ``recurring``.
* ``announcements.recur_interval_minutes`` — reappearance interval, only
  meaningful for the ``recurring`` policy.
* ``announcements.audience`` — reserved targeting vocabulary (``all``
  today, so behaviour is unchanged).
* ``announcement_states`` — per-subject dismissal/seen rows. A subject is
  either a signed-in user or an anonymous browser device, so one subject's
  dismissal never affects another.

Existing rows keep the current behaviour: version 1, ``once_until_dismissed``
and ``all``. No data backfill is required.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ann_display_pol"
down_revision: str | None = "ann_kind_len50"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    if _is_sqlite():
        with op.batch_alter_table("announcements") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "version",
                    sa.Integer(),
                    server_default="1",
                    nullable=False,
                )
            )
            batch_op.add_column(
                sa.Column(
                    "display_policy",
                    sa.String(length=20),
                    server_default="once_until_dismissed",
                    nullable=False,
                )
            )
            batch_op.add_column(
                sa.Column("recur_interval_minutes", sa.Integer(), nullable=True)
            )
            batch_op.add_column(
                sa.Column(
                    "audience",
                    sa.String(length=20),
                    server_default="all",
                    nullable=False,
                )
            )
    else:
        op.add_column(
            "announcements",
            sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        )
        op.add_column(
            "announcements",
            sa.Column(
                "display_policy",
                sa.String(length=20),
                server_default="once_until_dismissed",
                nullable=False,
            ),
        )
        op.add_column(
            "announcements",
            sa.Column("recur_interval_minutes", sa.Integer(), nullable=True),
        )
        op.add_column(
            "announcements",
            sa.Column(
                "audience",
                sa.String(length=20),
                server_default="all",
                nullable=False,
            ),
        )

    op.create_table(
        "announcement_states",
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
        sa.Column("subject_type", sa.String(length=10), nullable=False),
        sa.Column("subject_id", sa.String(length=64), nullable=False),
        sa.Column(
            "announcement_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("announcements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "announcement_version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "subject_type",
            "subject_id",
            "announcement_id",
            "announcement_version",
            name="uq_announcement_states_subject_announcement_version",
        ),
    )
    op.create_index(
        "ix_announcement_states_subject",
        "announcement_states",
        ["subject_type", "subject_id"],
    )
    op.create_index(
        "ix_announcement_states_announcement",
        "announcement_states",
        ["announcement_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_announcement_states_announcement", table_name="announcement_states"
    )
    op.drop_index(
        "ix_announcement_states_subject", table_name="announcement_states"
    )
    op.drop_table("announcement_states")

    if _is_sqlite():
        with op.batch_alter_table("announcements") as batch_op:
            batch_op.drop_column("audience")
            batch_op.drop_column("recur_interval_minutes")
            batch_op.drop_column("display_policy")
            batch_op.drop_column("version")
    else:
        op.drop_column("announcements", "audience")
        op.drop_column("announcements", "recur_interval_minutes")
        op.drop_column("announcements", "display_policy")
        op.drop_column("announcements", "version")
