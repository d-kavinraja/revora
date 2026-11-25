"""Add persistent chat storage and independent chat-mode controls.

Revision ID: chatpersist001
Revises: kllm02_user_presence
Create Date: 2026-11-22 12:00:00.000000

Legacy feature_flags.chat is migrated to temporary availability and removed.
Persistent Chat starts disabled; Temporary Chat starts enabled when no legacy
chat flag exists. Stored conversations are owner-scoped and generation claims
are fenced by an opaque claim id.
"""

from collections.abc import Sequence
import json
import uuid

import sqlalchemy as sa
from alembic import op

revision: str = "chatpersist001"
down_revision: str | None = "kllm02_user_presence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("generation_claim_id", sa.Uuid(), nullable=True),
        sa.Column("generation_claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_chat_conversations_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_conversations")),
    )
    op.create_index("ix_chat_conversations_owner_updated", "chat_conversations", ["user_id", "updated_at"])
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("finish_reason", sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["chat_conversations.id"], name=op.f("fk_chat_messages_conversation_id_chat_conversations"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_messages")),
        sa.UniqueConstraint("conversation_id", "position", name="uq_chat_messages_conversation_position"),
    )
    op.create_index("ix_chat_messages_conversation", "chat_messages", ["conversation_id", "position"])

    conn = op.get_bind()
    legacy = conn.execute(
        sa.text("SELECT status, message FROM feature_flags WHERE key = 'chat'")
    ).first()
    temporary_enabled = legacy is None or legacy.status == "enabled"
    initial = {
        "temporary_enabled": temporary_enabled,
        "persistent_enabled": False,
        "temporary_message": getattr(legacy, "message", None) if legacy else None,
        "persistent_message": None,
    }
    settings = sa.table(
        "platform_settings",
        sa.column("id", sa.Uuid()),
        sa.column("key", sa.String(100)),
        sa.column("value", sa.JSON()),
        sa.column("updated_by", sa.Uuid()),
        sa.column("version", sa.Integer()),
    )
    existing = conn.execute(sa.select(settings.c.id).where(settings.c.key == "chat_modes")).first()
    if existing is None:
        conn.execute(
            settings.insert().values(
                id=uuid.uuid4(), key="chat_modes", value=initial, updated_by=None, version=1
            )
        )
    conn.execute(sa.text("DELETE FROM feature_flags WHERE key = 'chat'"))

    op.create_table(
        "chat_turn_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["chat_conversations.id"], name=op.f("fk_chat_turn_revisions_conversation_id_chat_conversations"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_turn_revisions")),
    )
    op.create_index("uq_chat_turn_revisions_claim", "chat_turn_revisions", ["claim_id"], unique=True)


def downgrade() -> None:
    # The legacy single flag cannot represent both independent controls. Restore
    # it from Temporary availability using portable SQLAlchemy row handling.
    conn = op.get_bind()
    setting = conn.execute(
        sa.text("SELECT value FROM platform_settings WHERE key = 'chat_modes'")
    ).first()
    exists = conn.execute(
        sa.text("SELECT id FROM feature_flags WHERE key = 'chat'")
    ).first()
    if setting is not None and exists is None:
        value = setting.value if isinstance(setting.value, dict) else json.loads(setting.value)
        flags = sa.table(
            "feature_flags",
            sa.column("id", sa.Uuid()),
            sa.column("key", sa.String(100)),
            sa.column("status", sa.String(20)),
            sa.column("message", sa.String(500)),
            sa.column("updated_by", sa.Uuid()),
        )
        conn.execute(flags.insert().values(
            id=uuid.uuid4(), key="chat",
            status="enabled" if value.get("temporary_enabled", True) else "disabled",
            message=value.get("temporary_message"), updated_by=None,
        ))
    op.drop_index("uq_chat_turn_revisions_claim", table_name="chat_turn_revisions")
    op.drop_table("chat_turn_revisions")
    op.drop_index("ix_chat_messages_conversation", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_conversations_owner_updated", table_name="chat_conversations")
    op.drop_table("chat_conversations")
    conn.execute(sa.text("DELETE FROM platform_settings WHERE key = 'chat_modes'"))
