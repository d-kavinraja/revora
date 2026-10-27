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
    features,
    keys,
    maintenance,
    models,
    overview,
    providers,
    repositories,
    reviews,
    users,
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
router.include_router(features.router, tags=["admin"])
router.include_router(maintenance.router, tags=["admin"])
router.include_router(announcements.router, tags=["admin"])
router.include_router(audit.router, tags=["admin"])
