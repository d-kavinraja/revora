from fastapi import APIRouter

from app.api.v1.endpoints import (
    analytics,
    api_keys,
    auth,
    cost,
    dashboard,
    health,
    llm,
    models,
    providers,
    repositories,
    review_lifecycle,
    review_stream,
    reviews,
    routing,
    ui_settings,
    usage,
    verification,
    webhooks,
)

api_router = APIRouter()
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(repositories.router, prefix="/repositories", tags=["repositories"])
# review_stream must precede reviews/review_lifecycle so the literal
# /reviews/stream route wins over /reviews/{review_id}.
api_router.include_router(review_stream.router, prefix="/reviews", tags=["review-stream"])
api_router.include_router(review_lifecycle.router, prefix="/reviews", tags=["review-lifecycle"])
api_router.include_router(reviews.router, prefix="/reviews", tags=["reviews"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(api_keys.router, prefix="/api-keys", tags=["api-keys"])
api_router.include_router(ui_settings.router, prefix="/ui/settings", tags=["ui-settings"])
api_router.include_router(providers.router, prefix="/providers", tags=["providers"])
api_router.include_router(usage.router, prefix="/platform-usage", tags=["usage"])
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(routing.router, prefix="/routing", tags=["routing"])
api_router.include_router(analytics.router, prefix="/platform-analytics", tags=["analytics"])
api_router.include_router(llm.router, prefix="/llm", tags=["llm"])
api_router.include_router(models.router, prefix="/models", tags=["models"])
api_router.include_router(cost.router, prefix="/cost", tags=["cost"])
api_router.include_router(verification.router, prefix="/verify", tags=["verification"])

