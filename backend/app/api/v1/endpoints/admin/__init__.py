"""Admin API package. Mounted at `/api/v1/admin` in `api/v1/router.py`.

Every handler must declare `Depends(get_current_admin)` (or the legacy
route guard `get_current_admin_or_403`); the parameterized authz tests
(B1–B4) fail if a route is added without it.
"""

from fastapi import APIRouter

from app.api.v1.endpoints.admin import (
    announcements,
    audit,
    auth,
    chat_modes,
    features,
    hosted_ollama,
    installations,
    keys,
    kllm,
    kllm_cloud,
    maintenance,
    models,
    overview,
    providers,
    repositories,
    reviews,
    speech,
    users,
    usage_analytics,
)

router = APIRouter()
router.include_router(auth.router, prefix="/auth", tags=["admin-auth"])
router.include_router(overview.router, tags=["admin"])
router.include_router(users.router, tags=["admin"])
router.include_router(repositories.router, tags=["admin"])
router.include_router(reviews.router, tags=["admin"])
router.include_router(providers.router, tags=["admin"])
router.include_router(keys.router, tags=["admin"])
router.include_router(models.router, tags=["admin"])
router.include_router(kllm.router, prefix="/kllm", tags=["admin"])
router.include_router(kllm_cloud.router, prefix="/kllm-cloud", tags=["admin"])
router.include_router(hosted_ollama.router, prefix="/hosted-ollama", tags=["admin"])
router.include_router(speech.router, prefix="/hosted-ollama", tags=["admin"])
router.include_router(features.router, tags=["admin"])
router.include_router(chat_modes.router, tags=["admin"])
router.include_router(installations.router, tags=["admin"])
router.include_router(maintenance.router, tags=["admin"])
router.include_router(usage_analytics.router, tags=["admin"])
router.include_router(announcements.router, tags=["admin"])
router.include_router(audit.router, tags=["admin"])
