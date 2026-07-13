import json
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from app.core.config import settings
from app.github.webhooks import github_webhook_service

router = APIRouter()

@router.post("/github")
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
    
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
        
    action = payload.get("action")

    # 4. Process asynchronously in the background
    background_tasks.add_task(
        github_webhook_service.process_webhook, event, action, payload, delivery_id
    )

    return {"status": "ok"}
