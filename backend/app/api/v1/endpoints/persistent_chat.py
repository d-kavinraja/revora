"""Owner-scoped APIs for Persistent Chat.

The temporary /chat contract is intentionally unchanged and memory-only.
Persistent APIs only expose stored records owned by the authenticated user.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.llm import llm_service
from app.api.v1.endpoints.chat import (
    FIRST_TOKEN_TIMEOUT_SECONDS,
    _unpack_completion,
)
from app.api.v1.endpoints.chat_stream_response import LeaseStreamingResponse
from app.core.deps import get_current_user, get_current_user_for_stream
from app.db.session import get_db
from app.models.persistent_chat import ChatConversation, ChatMessage
from app.models.user import User
from app.schemas.persistent_chat import (
    PersistentConversationCreate,
    PersistentConversationRename,
    PersistentConversationRead,
    PersistentConversationSummary,
    PersistentMessageCreate,
    PersistentMessageEdit,
    PersistentMessageRead,
    PersistentRegenerate,
)
from app.services import hosted_ollama_service, kllm_cloud_service, kllm_service
from app.services.chat_service import (
    STREAM_HEADERS,
    enforce_chat_limits,
    release_chat_lease,
    clamp_requested_max_tokens,
    resolve_max_tokens,
    safe_chat_error,
    stream_chat_sse,
    trim_chat_context,
)
from app.services.persistent_chat_service import (
    MAX_MESSAGES_PER_CONVERSATION,
    acquire_claim,
    add_text_usage_guard,
    append_message,
    lock_current_claim,
    check_user_text_quota,
    claim_is_current,
    create_conversation,
    delete_conversation,
    owned_conversation,
    release_claim,
    require_mode,
    recover_expired_revision,
    save_revision,
    _discard_revision,
    _restore_revision,
)
from app.services.hosted_ollama_service import HostedError
from app.services.kllm_cloud_service import KllmCloudError
from app.services.kllm_service import KllmError

router = APIRouter()


def _read_message(row: ChatMessage) -> PersistentMessageRead:
    return PersistentMessageRead(
        id=row.id,
        position=row.position,
        role=row.role,
        content=row.content,
        status=row.status,
        model=row.model,
        finish_reason=row.finish_reason,
        created_at=row.created_at,
    )


def _read_conversation(row: ChatConversation) -> PersistentConversationRead:
    return PersistentConversationRead(
        id=row.id,
        title=row.title,
        model=row.model,
        created_at=row.created_at,
        updated_at=row.updated_at,
        messages=[_read_message(message) for message in row.messages],
    )


async def _prepare_model(
    db: AsyncSession, model: str, provider_assertion: str | None,
    messages: list[dict[str, str]], max_tokens: int | None,
) -> tuple[str, str, list[dict[str, str]], int, int | None]:
    if kllm_cloud_service.is_cloud_key(model):
        if provider_assertion not in (None, kllm_cloud_service.PROVIDER_SLUG):
            raise HTTPException(status_code=400, detail="Provider does not match model.")
        try:
            ready = await kllm_cloud_service.ensure_model_ready(
                db, model, surface="chat"
            )
        except KllmCloudError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={
                    "code": exc.reason_code or exc.code,
                    "message": exc.message,
                },
            ) from exc
        provider = kllm_cloud_service.PROVIDER_SLUG
        # Keep the namespaced key: it is the only place the provider identity is
        # stored (ChatMessage/ChatConversation have no provider column), so
        # stripping it here would make follow-up turns look like local kLLM and
        # silently dispatch a Cloud conversation to the local gateway.
        canonical = model
    elif hosted_ollama_service.is_hosted_key(model):
        if provider_assertion not in (None, hosted_ollama_service.HOSTED_PROVIDER_SLUG):
            raise HTTPException(status_code=400, detail="Provider does not match model.")
        ready = await hosted_ollama_service.ensure_model_ready(db, model)
        provider = hosted_ollama_service.HOSTED_PROVIDER_SLUG
        canonical = model
    else:
        if provider_assertion not in (None, "kllm"):
            raise HTTPException(status_code=400, detail="Provider does not match model.")
        if not await kllm_service.is_enabled(db):
            raise HTTPException(status_code=503, detail=kllm_service.DISABLED_MESSAGE)
        canonical = kllm_service.canonical_model(model)
        ready = await kllm_service.ensure_model_ready(db, canonical)
        provider = "kllm"
    window = getattr(ready, "context_window", None)
    requested = clamp_requested_max_tokens(max_tokens, window)
    context = trim_chat_context(
        messages,
        strict_alternation=provider == hosted_ollama_service.HOSTED_PROVIDER_SLUG,
        context_window=window,
        requested_max_tokens=requested,
    )
    if not context:
        raise HTTPException(status_code=400, detail="A valid user message is required.")
    return canonical, provider, context, resolve_max_tokens(requested, window, context), window


async def _generate(
    db: AsyncSession,
    conversation: ChatConversation,
    user_id: uuid.UUID,
    claim_id: uuid.UUID,
    *,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float | None,
    reasoning_effort: str | None,
    stream: bool,
    request: Request,
    local_lease=None,
) -> Response:
    if stream:
        conversation_id = conversation.id

        async def checked_stream() -> AsyncIterator[str]:
            content_parts: list[str] = []
            completed = False
            terminal_error = False
            finish_reason: str | None = None
            terminal_frame: str | None = None
            from app.services.chat_service import sse_event
            stream_factory = None
            is_cloud = kllm_cloud_service.is_cloud_key(model)
            if hosted_ollama_service.is_hosted_key(model):
                hosted_model = hosted_ollama_service.parse_hosted_key(model)
                stream_factory = lambda: llm_service.stream_hosted_completion(
                    hosted_model, messages, max_tokens=max_tokens,
                    temperature=temperature,
                )
            elif is_cloud:
                cloud_model = kllm_cloud_service.model_id_from_key(model)
                stream_factory = lambda: llm_service.stream_cloud_completion(
                    cloud_model, messages, max_tokens=max_tokens,
                    temperature=temperature,
                )
            try:
                async for frame in stream_chat_sse(
                    request, user_id=str(user_id), model=model, messages=messages,
                    max_tokens=max_tokens, temperature=temperature,
                    reasoning_effort=reasoning_effort, stream_factory=stream_factory,
                    provider_label=("kLLM Cloud" if is_cloud else "kLLM"),
                ):
                    still_current = await claim_is_current(
                        db, user_id, conversation_id, claim_id
                    )
                    await db.rollback()
                    if not still_current:
                        await db.rollback()
                        return
                    try:
                        data = json.loads(frame.removeprefix("data: ").strip())
                    except (ValueError, AttributeError):
                        data = {}
                    if data.get("type") == "delta":
                        content_parts.append(data.get("content", ""))
                    elif data.get("type") == "done":
                        finish_reason = data.get("finish_reason")
                        completed = finish_reason != "incomplete"
                        terminal_frame = frame
                        continue
                    elif data.get("type") == "error":
                        terminal_error = True
                    yield frame
                await add_text_usage_guard(db, user_id)
                if not await lock_current_claim(db, user_id, conversation_id, claim_id):
                    await db.rollback()
                    return
                if not completed or terminal_error:
                    if terminal_error or not completed:
                        await _restore_revision(db, conversation_id, claim_id)
                        await db.rollback()
                    if terminal_frame is not None:
                        yield terminal_frame
                    return
                conversation = await owned_conversation(db, user_id, conversation_id, lock=True)
                output = "".join(content_parts)
                await check_user_text_quota(db, user_id, output)
                stored_count = await db.scalar(
                    select(func.count()).select_from(ChatMessage).where(
                        ChatMessage.conversation_id == conversation.id
                    )
                )
                if int(stored_count or 0) >= MAX_MESSAGES_PER_CONVERSATION:
                    raise HTTPException(status_code=409, detail="This conversation has reached the 500-message limit.")
                conversation = await owned_conversation(db, user_id, conversation_id, lock=True)
                conversation.model = model
                await append_message(
                    db, conversation, role="assistant", content=output,
                    model=model,
                    status="truncated" if finish_reason == "length" else "complete",
                    finish_reason=finish_reason,
                )
                await _discard_revision(db, claim_id)
                await db.commit()
                if terminal_frame is not None:
                    yield terminal_frame
            except asyncio.CancelledError:
                await db.rollback()
                try:
                    await _restore_revision(db, conversation_id, claim_id)
                except Exception:
                    pass
                raise
            except Exception as exc:
                await db.rollback()
                try:
                    await _restore_revision(db, conversation_id, claim_id)
                except Exception:
                    pass
                code, message = safe_chat_error(
                    exc,
                    display_model=model,
                    provider_label="kLLM Cloud" if is_cloud else "kLLM",
                )
                yield sse_event({"type": "error", "code": code, "message": message})

        async def close_generation() -> None:
            try:
                await db.rollback()
            except Exception:
                pass
            try:
                await _restore_revision(db, conversation_id, claim_id)
            except Exception:
                pass
            await release_claim(db, user_id, conversation_id, claim_id)
            if local_lease is not None:
                await release_chat_lease(local_lease)

        return LeaseStreamingResponse(
            checked_stream(),
            on_close=close_generation,
            media_type="text/event-stream; charset=utf-8",
            headers=STREAM_HEADERS,
        )

    try:
        if hosted_ollama_service.is_hosted_key(model):
            result = await llm_service.complete_hosted(
                hosted_ollama_service.parse_hosted_key(model), messages,
                max_tokens=max_tokens, temperature=temperature,
                timeout=FIRST_TOKEN_TIMEOUT_SECONDS,
            )
        elif kllm_cloud_service.is_cloud_key(model):
            result = await llm_service.complete_cloud(
                kllm_cloud_service.model_id_from_key(model), messages,
                max_tokens=max_tokens, temperature=temperature,
                timeout=FIRST_TOKEN_TIMEOUT_SECONDS,
            )
        else:
            result = await llm_service.complete_managed(
                model, messages, max_tokens=max_tokens, temperature=temperature,
                reasoning_effort=reasoning_effort,
                timeout=FIRST_TOKEN_TIMEOUT_SECONDS,
            )
        await add_text_usage_guard(db, user_id)
        if not await lock_current_claim(db, user_id, conversation.id, claim_id):
            await db.rollback()
            raise HTTPException(status_code=404, detail="Conversation not found.")
        content, _input_tokens, _output_tokens, finish = _unpack_completion(result)
        await check_user_text_quota(db, user_id, content)
        stored_count = await db.scalar(
            select(func.count()).select_from(ChatMessage).where(
                ChatMessage.conversation_id == conversation.id
            )
        )
        if int(stored_count or 0) >= MAX_MESSAGES_PER_CONVERSATION:
            raise HTTPException(status_code=409, detail="This conversation has reached the 500-message limit.")
        conversation.model = model
        await append_message(
            db, conversation, role="assistant", content=content, model=model,
            status="complete" if finish != "length" else "truncated", finish_reason=finish,
        )
        await db.commit()
        return JSONResponse({"content": content, "model": model, "finish_reason": finish})
    except Exception:
        await db.rollback()
        raise
    finally:
        await release_claim(db, user_id, conversation.id, claim_id)


@router.get("/conversations", response_model=list[PersistentConversationSummary])
async def list_conversations(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user),
):
    rows = (await db.execute(
        select(ChatConversation).where(ChatConversation.user_id == current_user.id)
        .options(selectinload(ChatConversation.messages))
        .order_by(ChatConversation.updated_at.desc())
    )).scalars().unique().all()
    return [PersistentConversationSummary(
        id=row.id, title=row.title, model=row.model, created_at=row.created_at,
        updated_at=row.updated_at, message_count=len(row.messages),
    ) for row in rows]


@router.post("/conversations", response_model=PersistentConversationRead, status_code=201)
async def new_conversation(
    data: PersistentConversationCreate,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user),
):
    await require_mode(db, "persistent")
    row = await create_conversation(db, current_user.id, data.title, data.model)
    return PersistentConversationRead(
        id=row.id,
        title=row.title,
        model=row.model,
        created_at=row.created_at,
        updated_at=row.updated_at,
        messages=[],
    )


@router.get("/conversations/{conversation_id}", response_model=PersistentConversationRead)
async def get_conversation(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user),
):
    row = await owned_conversation(db, current_user.id, conversation_id)
    try:
        await recover_expired_revision(db, row.id)
    except Exception:
        await db.rollback()
        raise
    await db.refresh(row, attribute_names=["messages"])
    return _read_conversation(row)


@router.patch("/conversations/{conversation_id}", response_model=PersistentConversationSummary)
async def rename_conversation(
    conversation_id: uuid.UUID,
    data: PersistentConversationRename,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_mode(db, "persistent")
    row = await owned_conversation(db, current_user.id, conversation_id, lock=True)
    row.title = data.title.strip()
    if not row.title:
        raise HTTPException(status_code=422, detail="Conversation title cannot be empty.")
    row.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(row)
    count = await db.scalar(
        select(func.count()).select_from(ChatMessage).where(ChatMessage.conversation_id == row.id)
    )
    return PersistentConversationSummary(
        id=row.id,
        title=row.title,
        model=row.model,
        created_at=row.created_at,
        updated_at=row.updated_at,
        message_count=int(count or 0),
    )


@router.delete("/conversations/{conversation_id}", status_code=204)
async def remove_conversation(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user),
):
    try:
        await delete_conversation(db, current_user.id, conversation_id)
    except Exception as exc:
        from sqlalchemy.exc import IntegrityError
        if isinstance(exc, IntegrityError):
            await db.rollback()
            return Response(status_code=204)
        await db.rollback()
        raise
    return Response(status_code=204)


@router.post("/conversations/{conversation_id}/messages")
async def create_message(
    conversation_id: uuid.UUID,
    data: PersistentMessageCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_for_stream),
):
    await require_mode(db, "persistent")
    await add_text_usage_guard(db, current_user.id)
    row = await owned_conversation(db, current_user.id, conversation_id, lock=True)
    await recover_expired_revision(db, row.id)
    row = await owned_conversation(db, current_user.id, conversation_id, lock=True)
    messages = (await db.execute(
        select(ChatMessage).where(ChatMessage.conversation_id == row.id)
        .order_by(ChatMessage.position).with_for_update()
    )).scalars().all()
    if len(messages) + 2 > MAX_MESSAGES_PER_CONVERSATION:
        raise HTTPException(status_code=409, detail={"code": "message_quota", "message": "This conversation has reached the 500-message limit."})
    await check_user_text_quota(db, current_user.id, data.content)
    model, provider, context, max_tokens, _window = await _prepare_model(
        db, data.model, None, [*({"role": msg.role, "content": msg.content} for msg in messages), {"role": "user", "content": data.content}], data.max_tokens,
    )
    local_lease = await enforce_chat_limits(str(current_user.id), str(row.id))
    try:
        claim = await acquire_claim(db, current_user.id, row.id)
    except Exception:
        await release_chat_lease(local_lease)
        raise
    try:
        await append_message(db, row, role="user", content=data.content, model=model)
        await db.commit()
        return await _generate(
            db, row, current_user.id, claim, model=model, messages=context,
            max_tokens=max_tokens, temperature=data.temperature,
            reasoning_effort=data.reasoning_effort, stream=True, request=request,
            local_lease=local_lease,
        )
    except Exception:
        await db.rollback()
        await release_claim(db, current_user.id, row.id, claim)
        await release_chat_lease(local_lease)
        raise


async def _replace_turn(
    conversation_id: uuid.UUID,
    target_message_id: uuid.UUID,
    *,
    content: str | None,
    model_override: str | None,
    request: Request,
    db: AsyncSession,
    current_user: User,
):
    await require_mode(db, "persistent")
    await add_text_usage_guard(db, current_user.id)
    row = await owned_conversation(db, current_user.id, conversation_id, lock=True)
    await recover_expired_revision(db, row.id)
    row = await owned_conversation(db, current_user.id, conversation_id, lock=True)
    messages = (await db.execute(
        select(ChatMessage).where(ChatMessage.conversation_id == row.id)
        .order_by(ChatMessage.position).with_for_update()
    )).scalars().all()
    index = next((i for i, msg in enumerate(messages) if msg.id == target_message_id), None)
    if index is None:
        raise HTTPException(status_code=404, detail="Message not found.")
    target = messages[index]
    if content is not None and target.role != "user":
        raise HTTPException(status_code=400, detail="Only user messages can be edited.")
    if content is None and target.role != "assistant":
        raise HTTPException(status_code=400, detail="Only assistant messages can be regenerated.")
    user_index = index if content is not None else index - 1
    if user_index < 0 or messages[user_index].role != "user":
        raise HTTPException(status_code=409, detail="The stored turn is incomplete and cannot be replaced.")
    selected_model = model_override or row.model or messages[index].model or messages[user_index].model
    if not selected_model:
        raise HTTPException(status_code=409, detail="Select a model before replacing this turn.")
    prior_suffix = messages[user_index:]
    if user_index + 2 > MAX_MESSAGES_PER_CONVERSATION:
        raise HTTPException(status_code=409, detail={"code": "message_quota", "message": "This conversation has reached the 500-message limit."})
    original = [{"role": msg.role, "content": msg.content} for msg in messages[:user_index]]
    replacement = content if content is not None else messages[user_index].content
    request_messages = [*original, {"role": "user", "content": replacement}]
    canonical, provider, context, max_tokens, _window = await _prepare_model(
        db, selected_model, None, request_messages, None,
    )
    replacing_bytes = sum(msg.content_bytes for msg in prior_suffix)
    await check_user_text_quota(db, current_user.id, replacement, replacing_bytes)
    local_lease = await enforce_chat_limits(str(current_user.id), str(row.id))
    try:
        claim = await acquire_claim(db, current_user.id, row.id)
    except Exception:
        await release_chat_lease(local_lease)
        raise
    try:
        await save_revision(db, row.id, claim, messages)
        await db.execute(delete(ChatMessage).where(ChatMessage.id.in_([msg.id for msg in prior_suffix])))
        await append_message(db, row, role="user", content=replacement, model=canonical)
        # Commit the undo snapshot and replacement before remote inference, so a
        # worker crash is recoverable and the DB connection is not held upstream.
        await db.commit()
        return await _generate(
            db, row, current_user.id, claim, model=canonical, messages=context,
            max_tokens=max_tokens, temperature=None, reasoning_effort=None,
            stream=True, request=request, local_lease=local_lease,
        )
    except Exception:
        await db.rollback()
        await _restore_revision(db, row.id, claim)
        await release_claim(db, current_user.id, row.id, claim)
        await release_chat_lease(local_lease)
        raise


@router.put("/conversations/{conversation_id}/messages/{message_id}")
async def edit_message(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    data: PersistentMessageEdit,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_for_stream),
):
    return await _replace_turn(
        conversation_id, message_id, content=data.content, model_override=data.model,
        request=request, db=db, current_user=current_user,
    )


@router.post("/conversations/{conversation_id}/messages/{message_id}/regenerate")
async def regenerate_message(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    data: PersistentRegenerate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_for_stream),
):
    return await _replace_turn(
        conversation_id, message_id, content=None, model_override=data.model,
        request=request, db=db, current_user=current_user,
    )
