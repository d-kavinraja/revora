'''Admin controls for private speech-to-text.

Mounted at ``/api/v1/admin/hosted-ollama/speech`` so it sits beside the
existing Hosted models controls. The service URL and both tokens are
server-side only and never appear in a response. Speech is disabled by
default and requires the environment switch AND this admin toggle.
'''

# No `from __future__ import annotations`: these handlers keep ordinary
# annotations compatible with the app's rate-limit wrapper conventions.
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps_admin import get_current_admin
from app.db.session import get_db
from app.models.admin import AdminUser
from app.schemas.speech import (
    AdminSpeechStatus,
    AdminSpeechUpdate,
    SpeechEngineInfo,
    SpeechServiceInfo,
)
from app.services import speech_settings
from app.services.speech_client import speech_client
from app.services.admin_audit import admin_audit

router = APIRouter()


def _engine_info() -> SpeechEngineInfo:
    return SpeechEngineInfo(
        model='tiny.en',
        device='cpu',
        compute_type='int8',
        language='en',
        max_concurrent_inferences=1,
    )


async def _status_payload(db: AsyncSession) -> AdminSpeechStatus:
    state = await speech_settings.get_state(db, force=True)
    health = await speech_client.health()
    return AdminSpeechStatus(
        enabled=bool(state['enabled']),
        environment_enabled=bool(settings.REVORA_SPEECH_ENABLED),
        version=int(state['version']),
        max_recording_seconds=int(state['max_recording_seconds']),
        max_audio_mb=int(state['max_audio_mb']),
        queue_timeout_s=int(state['queue_timeout_s']),
        engine=_engine_info(),
        service=SpeechServiceInfo(**health),
    )


@router.get('/speech', response_model=AdminSpeechStatus)
async def get_speech_status(
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Current speech policy plus private-service health (no secrets)."""
    del current_admin
    return await _status_payload(db)


@router.put('/speech', response_model=AdminSpeechStatus)
async def update_speech_status(
    request: Request,
    data: AdminSpeechUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Persist speech policy with optimistic concurrency and an audit row."""
    if data.enabled and not settings.REVORA_SPEECH_ENABLED:
        raise HTTPException(
            status_code=409,
            detail={
                'code': 'speech_disabled',
                'message': 'Speech is disabled by the backend environment.',
            },
        )
    if data.enabled and not speech_client.configured:
        raise HTTPException(
            status_code=409,
            detail={
                'code': 'speech_not_configured',
                'message': 'Configure the private speech service before enabling speech.',
            },
        )

    try:
        state, prior = await speech_settings.update_state(
            db,
            actor_id=current_admin.id,
            enabled=data.enabled,
            max_recording_seconds=data.max_recording_seconds,
            max_audio_mb=data.max_audio_mb,
            queue_timeout_s=data.queue_timeout_s,
            expected_version=data.version,
        )
    except speech_settings.SpeechVersionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                'code': 'version_conflict',
                'message': str(exc),
                'current_version': exc.current,
            },
        ) from None

    if prior['enabled'] != state['enabled']:
        action = (
            'admin.speech_enabled' if state['enabled'] else 'admin.speech_disabled'
        )
    else:
        action = 'admin.speech_updated'
    await admin_audit(
        db,
        action=action,
        entity_type='platform_setting',
        entity_id=speech_settings.SPEECH_KEY,
        admin=current_admin,
        request=request,
        details={
            'enabled': bool(state['enabled']),
            'max_recording_seconds': int(state['max_recording_seconds']),
            'max_audio_mb': int(state['max_audio_mb']),
            'queue_timeout_s': int(state['queue_timeout_s']),
            'version': int(state['version']),
        },
        commit=False,
    )
    await db.commit()
    return await _status_payload(db)
