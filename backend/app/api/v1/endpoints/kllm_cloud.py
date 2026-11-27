"""User-facing kLLM Cloud status (mounted at ``/api/v1/kllm-cloud``).

Read-only and quota-free: provider state, attribution and the models the
administrator approved for Chat and/or Reviews. The relay URL, credentials,
account identities, aliases, media models and backend residency are never
returned here - those stay in the admin namespace.
"""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.deps_flags import require_feature
from app.db.session import get_db
from app.models.user import User
from app.services import kllm_cloud_service

router = APIRouter()

ATTRIBUTION = "Managed by Revora"


class CloudModelStatus(BaseModel):
    key: str
    model_id: str
    display_name: str
    description: str | None = None
    category: str
    context_window: int | None = None
    vision: bool = False
    tags: list[str] = []
    chat_enabled: bool = False
    review_enabled: bool = False
    # Readiness is per surface: Chat and Review are independent gates, so the
    # UI must never infer one from the other. ``ready`` / ``reason_code`` stay
    # as Chat aliases for older clients.
    chat_ready: bool = False
    review_ready: bool = False
    chat_reason_code: str = "unknown"
    review_reason_code: str = "unknown"
    ready: bool = False
    reason_code: str = "unknown"


class CloudStatusResponse(BaseModel):
    provider: str
    name: str
    attribution: str
    enabled: bool
    configured: bool
    reachable: bool
    stale: bool
    state: str
    reason: str
    last_success_at: str | None = None
    models: list[CloudModelStatus]
    counts: dict[str, int]


def _model(row: Any, snapshot: Any) -> CloudModelStatus:
    chat_ready, chat_reason = kllm_cloud_service.surface_readiness(
        snapshot, row, surface="chat"
    )
    review_ready, review_reason = kllm_cloud_service.surface_readiness(
        snapshot, row, surface="review"
    )
    return CloudModelStatus(
        key=row.key,
        model_id=row.model_id,
        display_name=row.display_name,
        description=row.description,
        category=row.kind,
        context_window=row.context_window,
        vision=row.vision,
        tags=list(row.tags),
        chat_enabled=bool(row.approved and not row.disabled and row.chat_enabled),
        review_enabled=bool(
            row.approved and not row.disabled and row.review_enabled
        ),
        chat_ready=chat_ready,
        review_ready=review_ready,
        chat_reason_code=chat_reason,
        review_reason_code=review_reason,
        ready=chat_ready,
        reason_code=chat_reason,
    )


@router.get("/status", response_model=CloudStatusResponse)
async def get_cloud_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_feature("kllm_cloud_page")),
):
    """Provider state plus the approved Chat/Review catalogue (read-only)."""
    snapshot = await kllm_cloud_service.get_snapshot(db, surface="chat")
    models = [
        _model(m, snapshot)
        for m in snapshot.models
        if m.kind == "chat" and m.approved and not m.disabled
    ]
    return CloudStatusResponse(
        provider=kllm_cloud_service.PROVIDER_SLUG,
        name=kllm_cloud_service.PROVIDER_NAME,
        attribution=ATTRIBUTION,
        enabled=snapshot.enabled,
        configured=snapshot.configured,
        reachable=snapshot.reachable,
        stale=snapshot.stale,
        state=snapshot.state,
        reason=snapshot.reason,
        last_success_at=(
            snapshot.last_success_at.isoformat()
            if snapshot.last_success_at
            else None
        ),
        models=models,
        counts=snapshot.counts,
    )
