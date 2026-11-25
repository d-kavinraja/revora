"""Persistent Chat API and storage integrity tests (no real inference)."""

from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.api.v1.endpoints import persistent_chat as persistent_endpoint
from app.services.chat_service import sse_event

from app.models.persistent_chat import ChatConversation, ChatMessage, ChatTurnRevision
from app.models.user import User
from app.services import persistent_chat_service as persistent_service
from app.services.platform_settings import platform_settings_service

MODEL = "qwen3.8-27b"


async def enable_persistent(db, enabled: bool = True) -> None:
    await platform_settings_service.set_chat_modes(
        db,
        {"temporary_enabled": True, "persistent_enabled": enabled},
    )
    await db.commit()


def test_persistent_chat_requires_auth(anon_client):
    response = anon_client.get("/api/v1/persistent-chat/conversations")
    assert response.status_code == 401


async def test_modes_are_independent_and_legacy_flag_is_not_an_admin_gate(client, test_db):
    await enable_persistent(test_db)
    await platform_settings_service.set_chat_modes(
        test_db, {"temporary_enabled": False, "persistent_enabled": True}
    )
    await test_db.commit()
    public = client.get("/api/v1/platform/chat-modes")
    assert public.status_code == 200
    assert public.json()["temporary_enabled"] is False
    assert public.json()["persistent_enabled"] is True
    temporary = client.post(
        "/api/v1/chat/completions",
        json={"model": MODEL, "messages": [{"role": "user", "content": "hello"}]},
    )
    assert temporary.status_code == 503
    assert client.post("/api/v1/persistent-chat/conversations", json={}).status_code == 201


async def test_persistent_create_gates_and_disabled_mode_retains_read_delete(client, test_db):
    create_url = "/api/v1/persistent-chat/conversations"
    disabled = client.post(create_url, json={"title": "first"})
    assert disabled.status_code == 503

    await enable_persistent(test_db)
    created = client.post(create_url, json={"title": "stored"})
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    await platform_settings_service.set_chat_modes(
        test_db,
        {"temporary_enabled": True, "persistent_enabled": False},
    )
    await test_db.commit()
    read = client.get(f"{create_url}/{conversation_id}")
    assert read.status_code == 200
    assert read.json()["title"] == "stored"
    blocked = client.post(
        f"{create_url}/{conversation_id}/messages",
        json={"model": MODEL, "content": "new"},
    )
    assert blocked.status_code == 503
    deleted = client.delete(f"{create_url}/{conversation_id}")
    assert deleted.status_code == 204


async def test_rename_conversation_is_owner_scoped_and_requires_enabled_mode(client, test_db):
    await enable_persistent(test_db)
    created = client.post(
        "/api/v1/persistent-chat/conversations",
        json={"title": "before", "model": MODEL},
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    renamed = client.patch(
        f"/api/v1/persistent-chat/conversations/{conversation_id}",
        json={"title": "  after  "},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "after"
    assert renamed.json()["model"] == MODEL
    assert renamed.json()["message_count"] == 0

    await platform_settings_service.set_chat_modes(
        test_db, {"temporary_enabled": True, "persistent_enabled": False}
    )
    await test_db.commit()
    blocked = client.patch(
        f"/api/v1/persistent-chat/conversations/{conversation_id}",
        json={"title": "blocked"},
    )
    assert blocked.status_code == 503

    await enable_persistent(test_db)
    invalid = client.patch(
        f"/api/v1/persistent-chat/conversations/{conversation_id}",
        json={"title": "   "},
    )
    assert invalid.status_code == 422


async def test_rename_hides_foreign_conversation(client, test_db):
    await enable_persistent(test_db)
    other = User(name="Other", email="rename-other@example.com", role="user", is_verified=True)
    test_db.add(other)
    await test_db.flush()
    conversation = ChatConversation(user_id=other.id, title="private")
    test_db.add(conversation)
    await test_db.commit()
    response = client.patch(
        f"/api/v1/persistent-chat/conversations/{conversation.id}",
        json={"title": "changed"},
    )
    assert response.status_code == 404


async def test_owner_scope_hides_foreign_conversation(client, test_db, mock_user):
    await enable_persistent(test_db)
    other = User(name="Other", email="other@example.com", role="user", is_verified=True)
    test_db.add(other)
    await test_db.flush()
    conversation = ChatConversation(user_id=other.id, title="private")
    test_db.add(conversation)
    await test_db.commit()
    response = client.get(f"/api/v1/persistent-chat/conversations/{conversation.id}")
    assert response.status_code == 404
    assert client.delete(f"/api/v1/persistent-chat/conversations/{conversation.id}").status_code == 404


async def test_conversation_and_text_quotas(client, test_db, mock_user, monkeypatch):
    await enable_persistent(test_db)
    monkeypatch.setattr(persistent_service, "MAX_CONVERSATIONS_PER_USER", 1)
    created = client.post("/api/v1/persistent-chat/conversations", json={"title": "one"})
    assert created.status_code == 201
    full = client.post("/api/v1/persistent-chat/conversations", json={"title": "two"})
    assert full.status_code == 409
    assert full.json()["detail"]["code"] == "conversation_quota"

    monkeypatch.setattr(persistent_service, "MAX_STORED_TEXT_BYTES_PER_USER", 3)
    owner_id = uuid.UUID(str(mock_user.id))
    with pytest.raises(HTTPException) as exc:
        await persistent_service.check_user_text_quota(test_db, owner_id, "four")
    assert exc.value.status_code == 413


async def test_message_quota_blocks_before_generation(client, test_db, monkeypatch):
    await enable_persistent(test_db)
    created = client.post("/api/v1/persistent-chat/conversations", json={})
    conversation_id = uuid.UUID(created.json()["id"])
    await enable_persistent(test_db)
    for position in range(1, persistent_service.MAX_MESSAGES_PER_CONVERSATION):
        test_db.add(ChatMessage(
            conversation_id=conversation_id,
            position=position,
            role="user" if position % 2 else "assistant",
            content="x",
            content_bytes=1,
            status="complete",
            model=MODEL,
        ))
    await test_db.commit()
    response = client.post(
        f"/api/v1/persistent-chat/conversations/{conversation_id}/messages",
        json={"model": MODEL, "content": "last"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "message_quota"


async def test_database_claim_is_single_flight_and_expiry_is_recoverable(test_db, mock_user):
    await enable_persistent(test_db)
    row = ChatConversation(user_id=mock_user.id, title="claim")
    test_db.add(row)
    await test_db.commit()
    row_id = uuid.UUID(str(row.id))
    owner_id = uuid.UUID(str(mock_user.id))
    claim = await persistent_service.acquire_claim(test_db, owner_id, row_id)
    with pytest.raises(HTTPException) as exc:
        await persistent_service.acquire_claim(test_db, owner_id, row_id)
    assert exc.value.status_code == 429
    refreshed = (await test_db.execute(
        select(ChatConversation).where(ChatConversation.id == row_id)
    )).scalars().first()
    assert refreshed is not None
    assert refreshed.generation_claim_id == claim
    await persistent_service.release_claim(test_db, owner_id, row_id, claim)


async def test_revision_restores_all_history_after_expired_generation(test_db, mock_user, monkeypatch):
    await enable_persistent(test_db)
    row = ChatConversation(user_id=mock_user.id, title="revision")
    test_db.add(row)
    await test_db.flush()
    original = [
        ChatMessage(conversation_id=row.id, position=1, role="user", content="old", content_bytes=3, status="complete"),
        ChatMessage(conversation_id=row.id, position=2, role="assistant", content="answer", content_bytes=6, status="complete"),
    ]
    test_db.add_all(original)
    await test_db.commit()
    claim = await persistent_service.acquire_claim(test_db, mock_user.id, row.id)
    await persistent_service.save_revision(test_db, row.id, claim, original)
    await test_db.execute(select(ChatMessage).where(ChatMessage.conversation_id == row.id).with_for_update())
    await test_db.execute(
        __import__("sqlalchemy").delete(ChatMessage).where(ChatMessage.conversation_id == row.id)
    )
    await persistent_service.append_message(test_db, row, role="user", content="replacement")
    await test_db.commit()

    stale = await test_db.get(ChatConversation, row.id)
    stale.generation_claim_expires_at = persistent_service.datetime.now(persistent_service.UTC) - persistent_service.timedelta(seconds=1)
    await test_db.commit()
    assert await persistent_service.recover_expired_revision(test_db, row.id) is True
    restored = (await test_db.execute(
        select(ChatMessage).where(ChatMessage.conversation_id == row.id).order_by(ChatMessage.position)
    )).scalars().all()
    assert [message.content for message in restored] == ["old", "answer"]
    assert await test_db.scalar(select(ChatTurnRevision.id).where(ChatTurnRevision.claim_id == claim)) is None


async def test_stream_failure_restores_replaced_history(test_db, mock_user, monkeypatch):
    await enable_persistent(test_db)

    async def keep_outer_test_transaction(*args, **kwargs):
        return None

    monkeypatch.setattr(test_db, "rollback", keep_outer_test_transaction)
    row = ChatConversation(user_id=mock_user.id, title="restore")
    test_db.add(row)
    await test_db.flush()
    original = [
        ChatMessage(conversation_id=row.id, position=1, role="user", content="old prompt", content_bytes=10, status="complete"),
        ChatMessage(conversation_id=row.id, position=2, role="assistant", content="old answer", content_bytes=10, status="complete"),
    ]
    test_db.add_all(original)
    await test_db.commit()
    conversation_id = uuid.UUID(str(row.id))
    owner_id = uuid.UUID(str(mock_user.id))
    claim = await persistent_service.acquire_claim(test_db, owner_id, conversation_id)
    await persistent_service.save_revision(test_db, conversation_id, claim, original)
    await test_db.execute(
        __import__("sqlalchemy").delete(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
    )
    current = await test_db.get(ChatConversation, conversation_id)
    await persistent_service.append_message(test_db, current, role="user", content="replacement")
    await test_db.commit()

    async def failed_stream(*args, **kwargs):
        yield sse_event({"type": "delta", "content": "partial"})
        yield sse_event({"type": "error", "code": "upstream", "message": "failed"})

    monkeypatch.setattr(persistent_endpoint, "stream_chat_sse", failed_stream)
    response = await persistent_endpoint._generate(
        test_db, current, owner_id, claim, model=MODEL,
        messages=[{"role": "user", "content": "replacement"}], max_tokens=32,
        temperature=None, reasoning_effort=None, stream=True,
        request=SimpleNamespace(is_disconnected=lambda: asyncio.sleep(0, result=False)),
    )
    frames = [frame async for frame in response.body_iterator]
    assert len(frames) == 2
    await response.aclose_and_release()
    restored = (await test_db.execute(
        select(ChatMessage).where(ChatMessage.conversation_id == conversation_id).order_by(ChatMessage.position)
    )).scalars().all()
    assert [message.content for message in restored] == ["old prompt", "old answer"]


async def test_delete_fences_active_generation_from_late_writes(test_db, mock_user, monkeypatch):
    await enable_persistent(test_db)
    row = ChatConversation(user_id=mock_user.id, title="delete")
    test_db.add(row)
    await test_db.flush()
    await persistent_service.append_message(test_db, row, role="user", content="prompt")
    await test_db.commit()
    conversation_id = uuid.UUID(str(row.id))
    owner_id = uuid.UUID(str(mock_user.id))
    claim = await persistent_service.acquire_claim(test_db, owner_id, conversation_id)
    await test_db.commit()

    async def late_stream(*args, **kwargs):
        yield sse_event({"type": "delta", "content": "late answer"})
        yield sse_event({"type": "done", "finish_reason": "stop"})

    monkeypatch.setattr(persistent_endpoint, "stream_chat_sse", late_stream)
    current = await test_db.get(ChatConversation, conversation_id)
    response = await persistent_endpoint._generate(
        test_db, current, owner_id, claim, model=MODEL,
        messages=[{"role": "user", "content": "prompt"}], max_tokens=32,
        temperature=None, reasoning_effort=None, stream=True,
        request=SimpleNamespace(is_disconnected=lambda: asyncio.sleep(0, result=False)),
    )
    await persistent_service.delete_conversation(test_db, owner_id, conversation_id)
    frames = [frame async for frame in response.body_iterator]
    assert frames == []
    await response.aclose_and_release()
    assert await test_db.scalar(
        select(func.count()).select_from(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
    ) == 0


async def test_admin_chat_mode_controls_are_available_to_platform_admin(admin_client):
    response = admin_client.get("/api/v1/admin/chat-modes")
    assert response.status_code == 200
    assert "persistent_enabled" in response.json()
