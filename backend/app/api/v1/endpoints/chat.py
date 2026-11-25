"""Temporary in-memory Chat API (kLLM + Revora-managed hosted Ollama).

No prompts, responses, conversation metadata, or usage records are persisted.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm import llm_service
from app.api.v1.endpoints.chat_stream_response import LeaseStreamingResponse
from app.core.deps import get_current_user, get_current_user_for_stream
from app.core.deps_flags import FeatureDisabledError, feature_message, require_feature
from app.db.session import AsyncSessionLocal, get_db
from app.models.user import User
from app.services import hosted_ollama_service, kllm_service
from app.services.chat_service import (
    FIRST_TOKEN_TIMEOUT_SECONDS,
    MAX_MESSAGE_CHARS,
    MAX_OUTPUT_TOKENS,
    MAX_REQUEST_CHARS,
    MAX_REQUEST_MESSAGES,
    STREAM_HEADERS,
    clamp_requested_max_tokens,
    enforce_chat_limits,
    release_chat_lease,
    resolve_max_tokens,
    safe_chat_error,
    stream_chat_sse,
    trim_chat_context,
)
from app.services.hosted_ollama_service import HostedError
from app.services.kllm_service import KllmError
from app.services.platform_settings import platform_settings_service
from app.services.persistent_chat_service import require_mode

logger = logging.getLogger(__name__)

router = APIRouter()


def _unpack_completion(result: Any) -> tuple[str, int, int, str | None]:
    """Accept a 3- or 4-tuple completion result.

    The clients now also return the provider finish reason, while existing
    callers and tests still mock the legacy ``(content, input_tokens,
    output_tokens)`` shape. A missing reason stays unknown instead of being
    replaced with a "stop" the provider never reported.
    """
    content = str(result[0])
    input_tokens = int(result[1])
    output_tokens = int(result[2])
    reason = result[3] if len(result) > 3 else None
    if not isinstance(reason, str) or not reason:
        reason = None
    return content, input_tokens, output_tokens, reason


# --- unified model catalog (kLLM + hosted) ----------------------------------


class ChatModelRead(BaseModel):
    key: str
    provider: str
    category: str
    display_name: str
    status: str
    loaded: bool
    ready: bool
    installed: bool = True
    admin_loadable: bool = False
    digest: str | None = None
    last_verified_at: str | None = None
    runtime_unknown: bool = False
    partial: bool = False
    load_state: str | None = None
    readiness: str = "unknown"
    reason_code: str = "unknown"
    context_window: int | None = None
    vision: bool = False
    tags: list[str] = []
    resident: bool = False
    backend_count: int = 0


class ChatProviderRead(BaseModel):
    provider: str
    enabled: bool
    configured: bool
    reachable: bool
    stale: bool = False
    error: str | None = None
    wake_enabled: bool = False
    waking: bool = False
    installed_count: int = 0
    loaded_count: int = 0
    last_verified_at: str | None = None
    discovery_partial: bool = False
    #: Backend-confirmed provider state; the UI renders banners from these.
    state: str = "unknown"
    reason: str = "unknown"
    discovery_ok: bool = False
    last_success_at: str | None = None
    cooldown_until: str | None = None


class ChatCatalogResponse(BaseModel):
    enabled: bool
    reachable: bool
    stale: bool
    generated_at: datetime
    providers: list[ChatProviderRead]
    models: list[ChatModelRead]


def _kllm_provider_state(snapshot: Any) -> tuple[str, str]:
    """Derive the kLLM provider state from the snapshot it already reports."""
    if not snapshot.enabled:
        return "disabled", "kllm_disabled"
    if not snapshot.configured:
        return "unconfigured", "kllm_not_configured"
    if not snapshot.reachable:
        return "unreachable", "kllm_unreachable"
    if snapshot.stale:
        return "stale", "kllm_state_stale"
    return "ready", "ready"


@router.get("/models", response_model=ChatCatalogResponse)
async def get_chat_models(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_feature("chat")),
):
    """Unified selectable-model catalog for Chat: kLLM + hosted Ollama.

    Hosted entries include the installed inventory reported by ``/api/tags`` and
    the runtime-loaded set reported by ``/api/ps``. Installed-but-unloaded
    models are listed so they are visible, but only an ``/api/ps``-confirmed
    model has ``ready=True`` and is selectable. Revora never auto-loads a model
    to satisfy a catalog refresh or a selection. The kLLM surface is unchanged.
    No endpoint URL, token or machine identifier is ever returned.
    """
    try:
        modes = await platform_settings_service.get_chat_modes(db)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Chat settings are unavailable.") from exc
    chat_enabled = bool(modes["temporary_enabled"] or modes["persistent_enabled"])
    generated_at = datetime.now(UTC)
    if not chat_enabled:
        return ChatCatalogResponse(
            enabled=False,
            reachable=False,
            stale=False,
            generated_at=generated_at,
            providers=[],
            models=[],
        )

    kllm_snapshot = await kllm_service.get_snapshot(db)
    hosted_snapshot = await hosted_ollama_service.get_snapshot(db)
    kllm_state, kllm_reason = _kllm_provider_state(kllm_snapshot)

    models: list[dict[str, Any]] = []
    for m in kllm_snapshot.models:
        row = m.as_dict()
        row["provider"] = "kllm"
        row["category"] = "kllm"
        row["display_name"] = m.key
        row["resident"] = False
        models.append(row)
    for m in hosted_snapshot.models:
        models.append(m.as_dict())

    providers = [
        ChatProviderRead(
            provider="kllm",
            enabled=kllm_snapshot.enabled,
            configured=kllm_snapshot.configured,
            reachable=kllm_snapshot.reachable,
            stale=kllm_snapshot.stale,
            error=kllm_snapshot.error,
            installed_count=0,
            loaded_count=len(kllm_snapshot.models),
            last_verified_at=kllm_snapshot.generated_at.isoformat(),
            state=kllm_state,
            reason=kllm_reason,
            discovery_ok=bool(
                kllm_snapshot.enabled
                and kllm_snapshot.reachable
                and not kllm_snapshot.stale
            ),
            last_success_at=(
                kllm_snapshot.generated_at.isoformat()
                if kllm_snapshot.reachable and not kllm_snapshot.stale
                else None
            ),
        ),
        ChatProviderRead(
            provider=hosted_ollama_service.HOSTED_PROVIDER_SLUG,
            enabled=hosted_snapshot.enabled,
            configured=hosted_snapshot.configured,
            reachable=hosted_snapshot.reachable,
            stale=hosted_snapshot.stale,
            error=hosted_snapshot.error,
            wake_enabled=hosted_snapshot.wake_enabled,
            waking=hosted_snapshot.waking,
            installed_count=hosted_snapshot.installed_count,
            loaded_count=hosted_snapshot.loaded_count,
            last_verified_at=hosted_snapshot.generated_at.isoformat(),
            discovery_partial=hosted_snapshot.partial,
            state=hosted_snapshot.state,
            reason=hosted_snapshot.reason,
            discovery_ok=hosted_snapshot.discovery_ok,
            last_success_at=hosted_snapshot.last_success_at,
            cooldown_until=hosted_snapshot.cooldown_until,
        ),
    ]

    enabled = kllm_snapshot.enabled or hosted_snapshot.enabled
    kllm_fresh = (
        kllm_snapshot.enabled and kllm_snapshot.reachable and not kllm_snapshot.stale
    )
    hosted_fresh = (
        hosted_snapshot.enabled
        and hosted_snapshot.reachable
        and not hosted_snapshot.stale
    )
    reachable = kllm_fresh or hosted_fresh
    return ChatCatalogResponse(
        enabled=enabled,
        reachable=reachable,
        stale=enabled and not reachable,
        generated_at=generated_at,
        providers=providers,
        models=models,
    )


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
    #: Optional client assertion of the provider. The model key prefix stays
    #: authoritative; a mismatching value is rejected instead of being trusted.
    provider: Literal["kllm", "hosted-ollama"] | None = None
    #: Optional client chat identifier. Additive and backward compatible: it
    #: is never persisted or authenticated against, it only makes one chat
    #: single-flight so a duplicate request cannot start a second generation.
    chat_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def _validate_shape(self) -> "ChatCompletionRequest":
        if not self.messages:
            raise ValueError("At least one message is required.")
        if self.messages[-1].role != "user":
            raise ValueError("The last message must be from the user.")
        total_chars = 0
        for index, message in enumerate(self.messages):
            if not message.content.strip():
                raise ValueError(f"Message {index + 1} cannot be empty.")
            total_chars += len(message.content)
        if total_chars > MAX_REQUEST_CHARS:
            raise ValueError("The conversation exceeds the maximum request size.")
        return self


async def _validate_request(
    request: ChatCompletionRequest, current_user: User
) -> tuple[str, str, list[dict[str, str]], int, str | None, int | None]:
    """Return ``(model_key, provider, context, max_tokens, effort, context_window)``.

    Hosted (namespaced) keys route to the Revora-managed Ollama provider; every
    other key keeps the existing kLLM pathway unchanged. Neither path ever
    substitutes a model or auto-loads one just to serve a selection.
    """
    async with AsyncSessionLocal() as db:
        await require_mode(db, "temporary")

        if hosted_ollama_service.is_hosted_key(request.model):
            if request.provider is not None and request.provider != hosted_ollama_service.HOSTED_PROVIDER_SLUG:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "provider_mismatch",
                        "message": "The selected model belongs to a different provider.",
                    },
                )
            try:
                ready_model = await hosted_ollama_service.ensure_model_ready(
                    db, request.model
                )
            except HostedError as exc:
                raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
            provider = hosted_ollama_service.HOSTED_PROVIDER_SLUG
            model_key = request.model
        else:
            if request.provider is not None and request.provider != "kllm":
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "provider_mismatch",
                        "message": "The selected model belongs to a different provider.",
                    },
                )
            if not await kllm_service.is_enabled(db):
                raise HTTPException(status_code=503, detail=kllm_service.DISABLED_MESSAGE)
            canonical = kllm_service.canonical_model(request.model)
            try:
                ready_model = await kllm_service.ensure_model_ready(db, canonical)
            except KllmError as exc:
                raise HTTPException(status_code=503, detail=exc.message) from exc
            provider = "kllm"
            model_key = canonical

    is_hosted = provider == hosted_ollama_service.HOSTED_PROVIDER_SLUG
    # One fitting pass for both providers. The ready model's own window is the
    # authority, so a long conversation is fitted locally instead of being
    # rejected upstream, and the same history is never cut to 20 turns.
    context_window = getattr(ready_model, "context_window", None)
    if not context_window:
        # The window is unknown, so the legacy caps apply. Log the fallback with
        # counts only (never content) so the conservative path is visible instead
        # of silently shaping the conversation.
        logger.info(
            "chat_context_window_unknown provider=%s model=%s messages=%s",
            provider,
            model_key,
            len(request.messages),
        )
    # Clamp a client override to the window before fitting: without this the
    # prompt can be squeezed down to the reserve and lose the conversation.
    requested_max_tokens = clamp_requested_max_tokens(request.max_tokens, context_window)
    context = trim_chat_context(
        request.messages,
        strict_alternation=is_hosted,
        context_window=context_window,
        requested_max_tokens=requested_max_tokens,
    )
    if not context:
        if context_window:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "prompt_too_long",
                    "message": "This conversation does not fit the selected model's "
                    "context window. Start a new chat or shorten your message.",
                },
            )
        raise HTTPException(status_code=400, detail="A valid user message is required.")
    max_tokens = resolve_max_tokens(requested_max_tokens, context_window, context)
    return (
        model_key,
        provider,
        context,
        max_tokens,
        request.reasoning_effort,
        context_window,
    )


@router.post("/completions")
async def create_chat_completion(
    request: ChatCompletionRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user_for_stream),
    _: None = Depends(require_feature("chat")),
):
    user_id = str(current_user.id)
    # Admission is owner-scoped: the returned lease belongs to this exact
    # request. It is released on EVERY path. A streaming response hands it to
    # LeaseStreamingResponse, which releases it after the response has really
    # finished (including a client disconnect); release_on_exit is only cleared
    # once that response is about to be returned. Validation, readiness, provider
    # mismatch and hosted-key failures release in the finally below, so one
    # failed attempt cannot lock the chat for the lease TTL.
    lease = await enforce_chat_limits(user_id, request.chat_id)
    release_on_exit = True
    # Bound before the try so the error handlers can always reference it.
    context_window: int | None = None
    try:
        (
            model,
            provider,
            messages,
            max_tokens,
            reasoning_effort,
            context_window,
        ) = await _validate_request(request, current_user)
        is_hosted = provider == hosted_ollama_service.HOSTED_PROVIDER_SLUG
        hosted_model = (
            hosted_ollama_service.parse_hosted_key(model) if is_hosted else None
        )

        if request.stream:
            stream_factory = None
            if is_hosted:
                def stream_factory():
                    return llm_service.stream_hosted_completion(
                        hosted_model,
                        messages,
                        max_tokens=max_tokens,
                        temperature=request.temperature,
                        context_window=context_window,
                    )
            # The response owns the lease from here on: it is released after the
            # body iterator is closed, never inside the generator. Build the
            # response first so a construction failure still releases here.
            response = LeaseStreamingResponse(
                stream_chat_sse(
                    http_request,
                    user_id=user_id,
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=request.temperature,
                    reasoning_effort=reasoning_effort,
                    stream_factory=stream_factory,
                ),
                on_close=lambda: release_chat_lease(lease),
                media_type="text/event-stream; charset=utf-8",
                headers=STREAM_HEADERS,
            )
            release_on_exit = False
            return response

        if is_hosted:
            content, input_tokens, output_tokens, finish_reason = _unpack_completion(
                await llm_service.complete_hosted(
                    hosted_model,
                    messages,
                    max_tokens=max_tokens,
                    temperature=request.temperature,
                    timeout=FIRST_TOKEN_TIMEOUT_SECONDS,
                    context_window=context_window,
                )
            )
        else:
            content, input_tokens, output_tokens, finish_reason = _unpack_completion(
                await llm_service.complete_managed(
                    model,
                    messages,
                    max_tokens=max_tokens,
                    temperature=request.temperature,
                    reasoning_effort=reasoning_effort,
                    timeout=FIRST_TOKEN_TIMEOUT_SECONDS,
                )
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
                # The provider reason, or null when it reported none. Never
                # hardcoded: a "length" stop must reach the client as truncation.
                "finish_reason": finish_reason,
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
    except HostedError as exc:
        if getattr(exc, "structured", False):
            # The upstream rejection was classified. Log redacted request shape
            # only (counts, reason code) and return a stable machine-readable code.
            logger.warning(
                "hosted_chat_rejected model=%s reason=%s path=%s messages=%s chars=%s "
                "max_tokens=%s context_window=%s",
                request.model,
                exc.reason_code,
                "stream" if request.stream else "complete",
                len(request.messages),
                sum(len(m.content) for m in request.messages),
                request.max_tokens,
                context_window if context_window is not None else "unknown",
            )
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.reason_code, "message": exc.message},
            ) from exc
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except KllmError as exc:
        raise HTTPException(status_code=503, detail=exc.message) from exc
    except Exception as exc:
        code, message = safe_chat_error(exc)
        logger.warning("chat_request_error code=%s error_type=%s", code, type(exc).__name__)
        raise HTTPException(status_code=503, detail=message) from exc
    finally:
        if release_on_exit:
            await release_chat_lease(lease)
