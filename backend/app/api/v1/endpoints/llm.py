import hashlib
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.security.content_guard import detect_injection, sanitize_messages
from app.services.cost_estimator import cost_estimator
from app.services.model_router import model_router
from app.services.retry_failover import retry_failover
from app.services.token_manager import token_manager
from app.services.usage_tracker import usage_tracker

router = APIRouter()


class LLMExecuteRequest(BaseModel):
    messages: list
    feature: str = "code_review"
    preferred_provider: str | None = None
    preferred_model: str | None = None
    api_key_id: str | None = None


class LLMExecuteResponse(BaseModel):
    content: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    estimated_cost_usd: float
    is_fallback: bool


@router.post("/execute", response_model=LLMExecuteResponse)
async def execute_llm(
    data: LLMExecuteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Execute an LLM call using the user's own API keys."""
    # Sanitize messages and detect injection
    sanitized_messages = sanitize_messages(data.messages)

    # Check for injection in user messages
    for msg in sanitized_messages:
        if msg.get("role") == "user":
            is_injection, patterns = detect_injection(msg.get("content", ""))
            if is_injection:
                raise HTTPException(
                    status_code=400,
                    detail="Potential prompt injection detected. Please revise your input.",
                )

    # Resolve provider: prefer explicit user preference, otherwise use routing
    provider = data.preferred_provider
    model = data.preferred_model
    api_key_id = data.api_key_id

    if not provider or not model:
        routes = await model_router.route(
            db, current_user.id, data.feature,
            data.preferred_provider, data.preferred_model,
        )
        if not routes:
            raise HTTPException(
                status_code=404,
                detail="No available routes. Add an API key for a supported provider.",
            )
        # Use the best route — single provider, no fallback
        best_route = routes[0]
        provider = best_route.provider
        model = best_route.model
        api_key_id = best_route.api_key_id

    start_time = time.time()
    request_id = hashlib.sha256(f"{current_user.id}:{time.time()}".encode()).hexdigest()[:16]

    try:
        result = await retry_failover.execute(
            user_id=current_user.id,
            provider=provider,
            model=model,
            messages=sanitized_messages,
            api_key_id=api_key_id,
        )

        if settings.USAGE_ANALYTICS_ENABLED:
            # Record token usage
            if result.input_tokens > 0 or result.output_tokens > 0:
                await token_manager.record_usage(
                    db=db,
                    user_id=current_user.id,
                    provider=result.provider,
                    model=result.model,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    input_cost_usd=cost_estimator.estimate(result.provider, result.input_tokens, 0),
                    output_cost_usd=cost_estimator.estimate(result.provider, 0, result.output_tokens),
                    feature=data.feature,
                    latency_ms=result.latency_ms,
                    api_key_id=uuid.UUID(api_key_id) if api_key_id else None,
                    request_id=request_id,
                    is_fallback=False,
                )

            # Record budget spend (atomic)
            await cost_estimator.record_spend(
                db, current_user.id, result.estimated_cost_usd,
                result.provider, data.feature,
            )

            # Log request for observability
            await usage_tracker.log_request(
                db=db,
                request_id=request_id,
                user_id=current_user.id,
                provider=result.provider,
                model=result.model,
                feature=data.feature,
                messages=sanitized_messages,
                status="success",
                latency_ms=result.latency_ms,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cost_usd=result.estimated_cost_usd,
                started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start_time)),
                response_text=result.content,
                was_fallback=result.is_fallback,
            )

        return result

    except Exception as e:
        if settings.USAGE_ANALYTICS_ENABLED:
            # Log failed request
            await usage_tracker.log_request(
                db=db,
                request_id=request_id,
                user_id=current_user.id,
                provider=data.preferred_provider or "unknown",
                model=data.preferred_model or "unknown",
                feature=data.feature,
                messages=sanitized_messages,
                status="error",
                latency_ms=(time.time() - start_time) * 1000,
                input_tokens=0,
                output_tokens=0,
                cost_usd=0,
                started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start_time)),
                error_type=type(e).__name__,
                error_message=str(e),
            )
        raise HTTPException(status_code=500, detail=str(e))
