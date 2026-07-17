import uuid
import time
import hashlib
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.model_router import model_router
from app.services.retry_failover import retry_failover
from app.services.token_manager import token_manager
from app.services.cost_estimator import cost_estimator
from app.services.usage_tracker import usage_tracker
from app.orchestrator.models import LLMResponse
from app.security.prompt_guard import sanitize_messages, detect_injection

router = APIRouter()


class LLMExecuteRequest(BaseModel):
    messages: list
    feature: str = "code_review"
    preferred_provider: Optional[str] = None
    preferred_model: Optional[str] = None
    api_key_id: Optional[str] = None


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
        if msg.get("role") == "user" and detect_injection(msg.get("content", "")):
            raise HTTPException(
                status_code=400,
                detail="Potential prompt injection detected. Please revise your input.",
            )

    routes = await model_router.route(
        db, current_user.id, data.feature,
        data.preferred_provider, data.preferred_model,
    )

    if not routes:
        raise HTTPException(
            status_code=404,
            detail="No available routes. Add an API key for a supported provider.",
        )

    route_tuples = [(r.provider, r.model, r.api_key_id) for r in routes]

    start_time = time.time()
    request_id = hashlib.sha256(f"{current_user.id}:{time.time()}".encode()).hexdigest()[:16]

    try:
        result = await retry_failover.execute_with_fallback(
            db=db,
            user_id=current_user.id,
            feature=data.feature,
            messages=sanitized_messages,
            routes=route_tuples,
        )

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
                api_key_id=uuid.UUID(route_tuples[0][2]) if route_tuples[0][2] else None,
                request_id=request_id,
                is_fallback=result.is_fallback,
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
