import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.github.webhooks import github_webhook_service
from app.middleware.rate_limit import limiter
from app.services.webhook_delivery_service import (
    COMPLETED,
    FAILED,
    process_delivery,
    record_delivery,
    requeue_delivery,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/github")
@limiter.limit("100/minute")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    # 1. Read raw body
    body = await request.body()

    # 2. Verify signature
    signature = request.headers.get("X-Hub-Signature-256")
    if not signature or not github_webhook_service.verify_signature(
        body, signature, settings.GITHUB_WEBHOOK_SECRET
    ):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # 3. Parse event
    event = request.headers.get("X-GitHub-Event")
    delivery_id = request.headers.get("X-GitHub-Delivery")
    if not event or not delivery_id:
        raise HTTPException(
            status_code=400,
            detail="Missing GitHub webhook event or delivery headers",
        )

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid webhook payload")

    action = payload.get("action")

    # 4. Persist BEFORE acknowledging. A 202 is only returned once the event
    #    is durable; if the insert fails, return 503 so GitHub retries instead
    #    of acknowledging work we could lose on a crash.
    try:
        delivery, created = await record_delivery(
            event, action, payload, delivery_id
        )
    except Exception:
        logger.exception("Failed to persist GitHub webhook delivery %s", delivery_id)
        raise HTTPException(
            status_code=503,
            detail="Webhook could not be persisted; please retry.",
        )
    if delivery is None:
        raise HTTPException(
            status_code=503,
            detail="Webhook could not be persisted; please retry.",
        )

    if not created and delivery.status == COMPLETED:
        return JSONResponse(
            status_code=202,
            content={
                "status": "duplicate",
                "delivery_id": delivery_id,
            },
        )
    if not created and delivery.status == FAILED:
        # GitHub explicitly redelivered an event whose retries were exhausted:
        # give it a fresh attempt budget instead of acknowledging a no-op.
        await requeue_delivery(delivery_id)

    # 5. Process asynchronously. Pending/failed rows are also recovered by the
    #    periodic loop started in the app lifespan.
    background_tasks.add_task(process_delivery, delivery_id)

    # Return 202 Accepted (not 200) to indicate async processing
    return JSONResponse(
        status_code=202,
        content={"status": "accepted", "delivery_id": delivery_id},
    )
