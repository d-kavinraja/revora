"""Platform-admin controls for independent chat modes."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps_admin import get_current_admin
from app.db.session import get_db
from app.middleware.rate_limit import limiter
from app.models.admin import AdminUser
from app.schemas.persistent_chat import ChatModeSettingsRead, ChatModeSettingsUpdate
from app.services.admin_audit import admin_audit
from app.services.platform_settings import platform_settings_service

router = APIRouter()


def _response(state: dict) -> ChatModeSettingsRead:
    return ChatModeSettingsRead(
        temporary_enabled=bool(state["temporary_enabled"]),
        persistent_enabled=bool(state["persistent_enabled"]),
        temporary_message=state.get("temporary_message"),
        persistent_message=state.get("persistent_message"),
        version=int(state.get("version") or 0),
    )


@router.get("/chat-modes", response_model=ChatModeSettingsRead)
async def get_chat_modes(
    db: AsyncSession = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
):
    try:
        return _response(await platform_settings_service.get_chat_modes(db))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Chat settings are unavailable.") from exc


@router.put("/chat-modes", response_model=ChatModeSettingsRead)
@limiter.limit("30/minute")
async def update_chat_modes(
    request: Request,
    data: ChatModeSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    new, prior, conflict = await platform_settings_service.set_chat_modes(
        db,
        {
            "temporary_enabled": data.temporary_enabled,
            "persistent_enabled": data.persistent_enabled,
            "temporary_message": data.temporary_message,
            "persistent_message": data.persistent_message,
        },
        admin_id=current_admin.id,
        expected_version=data.version,
    )
    if conflict is not None:
        raise HTTPException(status_code=409, detail="Chat mode settings changed since they were loaded. Reload and retry.")
    await admin_audit(
        db,
        action="admin.chat_modes_changed",
        entity_type="platform_setting",
        entity_id="chat_modes",
        admin=current_admin,
        request=request,
        details={
            "temporary_was_enabled": bool(prior.get("temporary_enabled")),
            "temporary_enabled": bool(new.get("temporary_enabled")),
            "persistent_was_enabled": bool(prior.get("persistent_enabled")),
            "persistent_enabled": bool(new.get("persistent_enabled")),
        },
        commit=False,
    )
    await db.commit()
    return _response(new)
