"""Feature-flag enforcement dependency (phase 6, §11.1).

`require_feature(key)` blocks gated endpoints with
`503 {"code": "feature_disabled", "message": ...}` for non-admins when the
flag is not `enabled`. App users with `role == "admin"` bypass every flag
(the admin console itself never depends on flags — §11.1/§18).

Server-side enforcement is the real gate; the frontend `<FeatureUnavailable>`
wrappers are cosmetic (§11.1). Flags are read through the shared 5-second
TTL cache in `platform_settings_service`; a missing row or an unreachable DB
fails open to `enabled`, preserving zero-state parity (B23).
"""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.platform_settings import platform_settings_service

#: User-facing fallback copy when a flag is not `enabled` and the admin has
#: not configured a message (§11.2 gives Model Lab its own wording).
DEFAULT_FLAG_MESSAGES: dict[str, str] = {
    "model_lab": "Model Lab is temporarily unavailable while we update the service.",
    "mouthmap": "MouthMap is temporarily unavailable while we update the service.",
}

GENERIC_FLAG_MESSAGE = "This feature is temporarily unavailable. Please try again later."


class FeatureDisabledError(Exception):
    """Raised when a non-admin hits an endpoint behind a disabled flag."""

    def __init__(self, key: str, message: str | None = None):
        self.key = key
        self.message = message or DEFAULT_FLAG_MESSAGES.get(key, GENERIC_FLAG_MESSAGE)
        super().__init__(self.message)


def feature_message(key: str, status: str, message: str | None = None) -> str:
    """User-facing message for a non-enabled flag (admin message wins)."""
    if message:
        return message
    if status == "coming_soon":
        return "This feature is coming soon."
    if status == "under_testing":
        return "This feature is under testing and will be available soon."
    if status == "maintenance":
        return DEFAULT_FLAG_MESSAGES.get(
            key, "This feature is under maintenance. Please try again later."
        )
    return DEFAULT_FLAG_MESSAGES.get(key, GENERIC_FLAG_MESSAGE)


def require_feature(key: str):
    """Dependency factory: block non-admins while `key` is not `enabled`."""

    async def dependency(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        if getattr(current_user, "role", "user") == "admin":
            return
        flag = await platform_settings_service.get_flag(key, db)
        status = flag.get("status") or "enabled"
        if status != "enabled":
            raise FeatureDisabledError(key, feature_message(key, status, flag.get("message")))

    return dependency
