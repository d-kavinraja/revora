"""Temporary in-memory kLLM chat API.

No prompts, responses, conversation metadata, or usage records are persisted.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, model_validator

from app.ai.llm import llm_service
from app.core.deps import get_current_user_for_stream
from app.core.deps_flags import FeatureDisabledError, feature_message
from app.db.session import AsyncSessionLocal
from app.models.user import User
from app.services import kllm_service
from app.services.chat_service import (
    FIRST_TOKEN_TIMEOUT_SECONDS,
    MAX_MESSAGE_CHARS,
    MAX_OUTPUT_TOKENS,
    MAX_REQUEST_MESSAGES,
    STREAM_HEADERS,
    enforce_chat_limits,
    release_chat_single_flight,
    resolve_max_tokens,
    safe_chat_error,
    stream_chat_sse,
    trim_chat_context,
)
from app.services.kllm_service import KllmError
from app.services.platform_settings import platform_settings_service

logger = logging.getLogger(__name__)

router = APIRouter()


class ChatMessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class ChatCompletionRequest(BaseModel):
    model: str = Field(min_length=1, max_length=128)
    messages: list[ChatMessageIn] = Field(min_length=1, max_length=MAX_REQUEST_MESSAGES)
    stream: bool = True
    max_tokens: int | None = Field(default=None, ge=1, le=MAX_OUTPUT_TOKENS)
    temperature: float | None = Field(default=None, ge=0, le=2)
    reasoning_effort: Literal["low", "medium", "high", "max"] | None = None

    @model_validator(mode="after")
    def _validate_shape(self) -> "ChatCompletionRequest":
        if not self.messages:
            raise ValueError("At least one message is required.")
        if self.messages[-1].role != "user":
            raise ValueError("The last message must be from the user.")
        for index, message in enumerate(self.messages):
            if not message.content.strip():
                raise ValueError(f"Message {index + 1} cannot be empty.")
        return self


async def _validate_request(
    request: ChatCompletionRequest, current_user: User
) -> tuple[str, list[dict[str, str]], int, str | None]:
    async with AsyncSessionLocal() as db:
        flag = await platform_settings_service.get_flag("chat", db)
        if getattr(current_user, "role", "user") != "admin" and flag.get("status") != "enabled":
            raise FeatureDisabledError(
                "chat",
                feature_message(
                    "chat",
                    str(flag.get("status") or "enabled"),
                    flag.get("message"),
                ),
            )
        if not await kllm_service.is_enabled(db):
            raise HTTPException(status_code=503, detail=kllm_service.DISABLED_MESSAGE)

        canonical = kllm_service.canonical_model(request.model)
        try:
            ready_model = await kllm_service.ensure_model_ready(db, canonical)
        except KllmError as exc:
            raise HTTPException(status_code=503, detail=exc.message) from exc

    context = trim_chat_context(request.messages)
    if not context:
        raise HTTPException(status_code=400, detail="A valid user message is required.")
    context_window = getattr(ready_model, "context_window", None)
    max_tokens = resolve_max_tokens(request.max_tokens, context_window, context)
    return canonical, context, max_tokens, request.reasoning_effort


@router.post("/completions")
async def create_chat_completion(
    request: ChatCompletionRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user_for_stream),
):
    user_id = str(current_user.id)
    await enforce_chat_limits(user_id)
    release_on_exit = not request.stream
    try:
        model, messages, max_tokens, reasoning_effort = await _validate_request(
            request, current_user
        )

        if request.stream:
            return StreamingResponse(
                stream_chat_sse(
                    http_request,
                    user_id=user_id,
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=request.temperature,
                    reasoning_effort=reasoning_effort,
                ),
                media_type="text/event-stream; charset=utf-8",
                headers=STREAM_HEADERS,
            )

        content, input_tokens, output_tokens = await llm_service.complete_managed(
            model,
            messages,
            max_tokens=max_tokens,
            temperature=request.temperature,
            reasoning_effort=reasoning_effort,
            timeout=FIRST_TOKEN_TIMEOUT_SECONDS,
        )
        logger.info(
            "chat_complete model=%s messages=%s chars=%s input_tokens=%s output_tokens=%s",
            model,
            len(messages),
            sum(len(m.get("content", "")) for m in messages),
            input_tokens,
            output_tokens,
        )
        return JSONResponse(
            {
                "content": content,
                "model": model,
                "finish_reason": "stop",
                "usage": {
                    "prompt_tokens": int(input_tokens),
                    "completion_tokens": int(output_tokens),
                },
            }
        )
    except FeatureDisabledError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "feature_disabled", "message": exc.message},
        ) from exc
    except HTTPException:
        raise
    except KllmError as exc:
        raise HTTPException(status_code=503, detail=exc.message) from exc
    except Exception as exc:
        code, message = safe_chat_error(exc)
        logger.warning("chat_request_error code=%s error_type=%s", code, type(exc).__name__)
        raise HTTPException(status_code=503, detail=message) from exc
    finally:
        if release_on_exit:
            await release_chat_single_flight(user_id)
