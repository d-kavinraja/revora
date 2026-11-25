"""Persistent conversation ownership, quotas and cross-worker claims."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.persistent_chat import ChatConversation, ChatMessage, ChatTurnRevision
from app.models.user import User
from app.services.platform_settings import platform_settings_service

MAX_CONVERSATIONS_PER_USER = 100
MAX_MESSAGES_PER_CONVERSATION = 500
MAX_STORED_TEXT_BYTES_PER_USER = 20 * 1024 * 1024
CLAIM_TTL_SECONDS = 660


def message_bytes(text: str) -> int:
    return len(text.encode("utf-8"))


async def require_mode(db: AsyncSession, mode: str) -> dict:
    try:
        state = await platform_settings_service.get_chat_modes(db)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Chat settings are unavailable.") from exc
    key = f"{mode}_enabled"
    if not state.get(key, False):
        raise HTTPException(
            status_code=503,
            detail={"code": "feature_disabled", "message": state.get(f"{mode}_message") or f"{mode.title()} Chat is unavailable."},
        )
    return state


async def owned_conversation(
    db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID, *, lock: bool = False
) -> ChatConversation:
    query = select(ChatConversation).where(
        ChatConversation.id == conversation_id,
        ChatConversation.user_id == user_id,
    )
    if lock:
        query = query.with_for_update()
    conversation = (await db.execute(query)).scalars().first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conversation


async def create_conversation(
    db: AsyncSession, user_id: uuid.UUID, title: str | None, model: str | None
) -> ChatConversation:
    # Serialize quota checks across this user's conversations on PostgreSQL.
    await db.execute(select(User.id).where(User.id == user_id).with_for_update())
    count = await db.scalar(
        select(func.count()).select_from(ChatConversation).where(ChatConversation.user_id == user_id)
    )
    if int(count or 0) >= MAX_CONVERSATIONS_PER_USER:
        raise HTTPException(status_code=409, detail={"code": "conversation_quota", "message": "You have reached the 100-conversation limit."})
    row = ChatConversation(user_id=user_id, title=(title or "New chat").strip()[:200], model=model)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def acquire_claim(
    db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> uuid.UUID:
    claim_id = uuid.uuid4()
    now = datetime.now(UTC)
    await owned_conversation(db, user_id, conversation_id, lock=True)
    result = await db.execute(
        update(ChatConversation)
        .where(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == user_id,
            (ChatConversation.generation_claim_id.is_(None))
            | (ChatConversation.generation_claim_expires_at <= now),
        )
        .values(
            generation_claim_id=claim_id,
            generation_claim_expires_at=now + timedelta(seconds=CLAIM_TTL_SECONDS),
        )
    )
    if result.rowcount != 1:
        raise HTTPException(status_code=429, detail="A response is already being generated for this conversation.")
    return claim_id


async def claim_is_current(
    db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID, claim_id: uuid.UUID
) -> bool:
    exists = await db.scalar(
        select(ChatConversation.id).where(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == user_id,
            ChatConversation.generation_claim_id == claim_id,
            ChatConversation.generation_claim_expires_at > datetime.now(UTC),
        )
    )
    return exists is not None


async def release_claim(
    db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID, claim_id: uuid.UUID
) -> None:
    await db.execute(
        update(ChatConversation)
        .where(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == user_id,
            ChatConversation.generation_claim_id == claim_id,
        )
        .values(generation_claim_id=None, generation_claim_expires_at=None)
    )
    await db.commit()


async def check_user_text_quota(
    db: AsyncSession, user_id: uuid.UUID, incoming: str, replacing_bytes: int = 0
) -> None:
    # Keep the quota read + following message writes in one transaction while
    # serializing writes by owner across workers.
    used = await db.scalar(
        select(func.coalesce(func.sum(ChatMessage.content_bytes), 0))
        .join(ChatConversation, ChatConversation.id == ChatMessage.conversation_id)
        .where(ChatConversation.user_id == user_id)
    )
    if int(used or 0) - replacing_bytes + message_bytes(incoming) > MAX_STORED_TEXT_BYTES_PER_USER:
        raise HTTPException(status_code=413, detail={"code": "stored_text_quota", "message": "Your stored chat text has reached the 20 MB limit. Delete conversations to make room."})


async def add_text_usage_guard(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Acquire the owner's row lock for an atomic stored-text quota check."""
    await db.execute(select(User.id).where(User.id == user_id).with_for_update())


async def append_message(
    db: AsyncSession,
    conversation: ChatConversation,
    *,
    role: str,
    content: str,
    model: str | None = None,
    status: str = "complete",
    finish_reason: str | None = None,
) -> ChatMessage:
    current = await db.scalar(
        select(func.max(ChatMessage.position)).where(ChatMessage.conversation_id == conversation.id)
    )
    row = ChatMessage(
        conversation_id=conversation.id,
        position=int(current or 0) + 1,
        role=role,
        content=content,
        content_bytes=message_bytes(content),
        status=status,
        model=model,
        finish_reason=finish_reason,
    )
    db.add(row)
    conversation.updated_at = datetime.now(UTC)
    return row


async def save_revision(
    db: AsyncSession, conversation_id: uuid.UUID, claim_id: uuid.UUID,
    messages: list[ChatMessage],
) -> None:
    snapshot = [
        {
            "id": str(message.id),
            "position": message.position,
            "role": message.role,
            "content": message.content,
            "content_bytes": message.content_bytes,
            "status": message.status,
            "model": message.model,
            "finish_reason": message.finish_reason,
            "created_at": message.created_at.isoformat(),
        }
        for message in messages
    ]
    db.add(ChatTurnRevision(conversation_id=conversation_id, claim_id=claim_id, snapshot=snapshot))
    await db.flush()


async def _discard_revision(db: AsyncSession, claim_id: uuid.UUID) -> None:
    await db.execute(delete(ChatTurnRevision).where(ChatTurnRevision.claim_id == claim_id))


async def lock_current_claim(
    db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID, claim_id: uuid.UUID
) -> bool:
    row = (await db.execute(
        select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == user_id,
            ChatConversation.generation_claim_id == claim_id,
            ChatConversation.generation_claim_expires_at > datetime.now(UTC),
        ).with_for_update()
    )).scalars().first()
    return row is not None


async def recover_expired_revision(db: AsyncSession, conversation_id: uuid.UUID) -> bool:
    now = datetime.now(UTC)
    row = (await db.execute(
        select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.generation_claim_id.is_not(None),
            ChatConversation.generation_claim_expires_at <= now,
        ).with_for_update()
    )).scalars().first()
    if row is None or row.generation_claim_id is None:
        return False
    return await _restore_revision(db, conversation_id, row.generation_claim_id)


async def _restore_revision(
    db: AsyncSession, conversation_id: uuid.UUID, claim_id: uuid.UUID
) -> bool:
    revision = (await db.execute(
        select(ChatTurnRevision).where(
            ChatTurnRevision.conversation_id == conversation_id,
            ChatTurnRevision.claim_id == claim_id,
        ).with_for_update()
    )).scalars().first()
    if revision is None:
        return False
    conversation = (await db.execute(
        select(ChatConversation).where(ChatConversation.id == conversation_id).with_for_update()
    )).scalars().first()
    if conversation is None or conversation.generation_claim_id != claim_id:
        return False
    await db.execute(delete(ChatMessage).where(ChatMessage.conversation_id == conversation_id))
    for item in revision.snapshot:
        db.add(ChatMessage(
            id=uuid.UUID(item["id"]), conversation_id=conversation_id,
            position=item["position"], role=item["role"], content=item["content"],
            content_bytes=item["content_bytes"], status=item["status"],
            model=item.get("model"), finish_reason=item.get("finish_reason"),
            created_at=datetime.fromisoformat(item["created_at"]),
        ))
    await db.flush()
    await db.execute(delete(ChatTurnRevision).where(ChatTurnRevision.claim_id == claim_id))
    conversation.generation_claim_id = None
    conversation.generation_claim_expires_at = None
    await db.commit()
    return True


async def delete_conversation(
    db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> None:
    await owned_conversation(db, user_id, conversation_id, lock=True)
    # Owner-scoped DELETE is the cancellation fence: active workers observe the
    # missing claim before applying any late result, and FK cascade removes data.
    await db.execute(
        delete(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == user_id,
        )
    )
    await db.commit()
