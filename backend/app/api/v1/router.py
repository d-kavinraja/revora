from fastapi import APIRouter
from app.api.v1.endpoints import webhooks, auth, repositories, reviews, dashboard, review_stream, api_keys, ui_settings

api_router = APIRouter()
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(repositories.router, prefix="/repositories", tags=["repositories"])
api_router.include_router(reviews.router, prefix="/reviews", tags=["reviews"])
api_router.include_router(review_stream.router, prefix="/reviews", tags=["review-stream"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(api_keys.router, prefix="/api-keys", tags=["api-keys"])
api_router.include_router(ui_settings.router, prefix="/ui/settings", tags=["ui-settings"])
