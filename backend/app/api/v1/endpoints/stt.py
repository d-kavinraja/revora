'''Authenticated, read-only speech-to-text proxy for the chat composer.

Audio is buffered only in this request, sent to the private Whisper service,
and discarded. No audio, transcript, request id or metadata is written to
the database, Redis, disk, logs, analytics or a job store. The response is
NDJSON so queued/processing states are observable without persistence.
'''

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect
from starlette.types import Receive, Scope, Send

from app.core.deps import get_current_user_readonly
from app.db.session import get_db
from app.models.user import User
from app.schemas.speech import SpeechConfigResponse, SpeechReadinessResponse
from app.services import speech_settings
from app.services.speech_admission import speech_admission
from app.services.speech_client import SpeechStream, speech_client
from app.services.speech_errors import SpeechAPIError, SpeechClientError

logger = logging.getLogger(__name__)

router = APIRouter()

MIB = 1024 * 1024
MAX_AUDIO_BYTES = 5 * MIB
UPLOAD_TIMEOUT_S = 30.0
ALLOWED_CONTENT_TYPES = {
    'audio/webm',
    'audio/ogg',
    'audio/mp4',
    'audio/wav',
    'audio/x-wav',
}

STREAM_HEADERS = {
    'Cache-Control': 'no-store, max-age=0',
    'Pragma': 'no-cache',
    'X-Accel-Buffering': 'no',
    'X-Content-Type-Options': 'nosniff',
}


class SpeechStreamingResponse(StreamingResponse):
    '''Release the admission lease even if the ASGI response is never iterated.

    A disconnect can win the race before Starlette starts the async body
    generator. Closing an unstarted async generator does not run its `finally`
    block, so the generator alone is not enough to guarantee that the global
    slot is freed. This wrapper owns the lease for the whole ASGI call.
    '''

    def __init__(
        self,
        content: AsyncIterator[str],
        *,
        lease,
        upstream: SpeechStream,
    ) -> None:
        super().__init__(
            content,
            media_type='application/x-ndjson',
            headers=STREAM_HEADERS,
        )
        self._lease = lease
        self._upstream = upstream

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            # Idempotent with the generator's own cleanup.
            speech_admission.release(self._lease)
            try:
                await self._upstream.close()
            except Exception:
                pass

_ALLOWED_EVENT_CODES = {
    'invalid_audio',
    'audio_too_long',
    'audio_too_large',
    'unsupported_audio_type',
    'no_speech',
    'speech_queue_full',
    'speech_queue_timeout',
    'speech_timeout',
    'speech_cancelled',
    'speech_upstream_error',
    'speech_unavailable',
}


def _base_content_type(value: str | None) -> str:
    return (value or '').split(';', 1)[0].strip().lower()


def _looks_like_audio(data: bytes, content_type: str) -> bool:
    if len(data) < 16:
        return False
    if content_type == 'audio/webm':
        return data.startswith(b'\x1a\x45\xdf\xa3')
    if content_type == 'audio/ogg':
        return data.startswith(b'OggS')
    if content_type in {'audio/wav', 'audio/x-wav'}:
        return data.startswith(b'RIFF') and data[8:12] == b'WAVE'
    if content_type == 'audio/mp4':
        return data[4:8] == b'ftyp'
    return False


async def _read_audio(request: Request, max_bytes: int) -> bytes:
    buffer = bytearray()
    try:
        async with asyncio.timeout(UPLOAD_TIMEOUT_S):
            async for chunk in request.stream():
                if not chunk:
                    continue
                if len(buffer) + len(chunk) > max_bytes:
                    raise SpeechAPIError(
                        'audio_too_large', 413, 'The recording is too large.'
                    )
                buffer.extend(chunk)
    except TimeoutError as exc:
        raise SpeechAPIError(
            'speech_timeout', 408, 'The recording upload timed out.'
        ) from exc
    except ClientDisconnect as exc:
        raise SpeechAPIError(
            'client_disconnected', 499, 'The client disconnected.'
        ) from exc
    if not buffer:
        raise SpeechAPIError('invalid_audio', 422, 'The recording was empty.')
    return bytes(buffer)


def _line(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n'


def _safe_event_code(code: str) -> str:
    return code if code in _ALLOWED_EVENT_CODES else 'speech_unavailable'


async def _stream_events(
    upstream: SpeechStream,
    lease,
) -> AsyncIterator[str]:
    try:
        async for event in upstream.events():
            kind = event.get('type')
            if kind in {'queued', 'processing'}:
                yield _line({'type': kind})
                continue
            if kind == 'result':
                yield _line({'type': 'result', 'text': event.get('text', '')})
                return
            if kind == 'error':
                yield _line(
                    {
                        'type': 'error',
                        'code': _safe_event_code(str(event.get('code') or '')),
                        'message': str(event.get('message') or 'Speech failed.')[:300],
                    }
                )
                return
        yield _line(
            {
                'type': 'error',
                'code': 'speech_upstream_error',
                'message': 'Speech service returned no result.',
            }
        )
    except SpeechClientError as exc:
        yield _line(
            {
                'type': 'error',
                'code': _safe_event_code(exc.code),
                'message': exc.message[:300],
            }
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        yield _line(
            {
                'type': 'error',
                'code': 'speech_upstream_error',
                'message': 'Speech service failed to process the request.',
            }
        )
    finally:
        # Free the local slot before any network cleanup so a disconnect or a
        # slow close cannot strand the per-user/global admission count.
        speech_admission.release(lease)
        try:
            await upstream.close()
        except Exception:
            # The upstream may already be gone.
            pass


@router.get('/config', response_model=SpeechConfigResponse)
async def get_speech_config(
    response: Response,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user_readonly),
) -> SpeechConfigResponse:
    response.headers['Cache-Control'] = 'no-store, max-age=0'
    try:
        state = await speech_settings.get_state(db, force=True)
    except Exception:
        logger.warning('speech settings unavailable; failing closed')
        raise SpeechAPIError(
            'speech_unavailable', 503, 'Speech is unavailable.'
        ) from None
    return SpeechConfigResponse(
        enabled=speech_settings.effective_enabled(state),
        max_recording_seconds=int(state['max_recording_seconds']),
        max_audio_mb=int(state['max_audio_mb']),
    )


@router.get('/status', response_model=SpeechReadinessResponse)
async def get_speech_status(
    response: Response,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user_readonly),
) -> SpeechReadinessResponse:
    response.headers['Cache-Control'] = 'no-store, max-age=0'
    try:
        state = await speech_settings.get_state(db, force=True)
    except Exception:
        logger.warning('speech settings unavailable; failing closed')
        return SpeechReadinessResponse(
            enabled=False,
            state='error',
            ready=False,
            max_recording_seconds=60,
            max_audio_mb=5,
        )
    enabled = speech_settings.effective_enabled(state)
    max_recording = int(state['max_recording_seconds'])
    max_audio = int(state['max_audio_mb'])
    if not enabled:
        return SpeechReadinessResponse(
            enabled=False,
            state='disabled',
            ready=False,
            max_recording_seconds=max_recording,
            max_audio_mb=max_audio,
        )
    health = await speech_client.health()
    return SpeechReadinessResponse(
        enabled=True,
        state=str(health.get('state') or 'unavailable'),
        ready=bool(health.get('ready')),
        max_recording_seconds=max_recording,
        max_audio_mb=max_audio,
    )


@router.post('/transcribe')
async def transcribe(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user_readonly),
) -> StreamingResponse:
    try:
        state = await speech_settings.get_state(db, force=True)
    except Exception:
        logger.warning('speech settings unavailable; failing closed')
        raise SpeechAPIError(
            'speech_unavailable', 503, 'Speech is unavailable.'
        ) from None
    if not speech_settings.effective_enabled(state):
        raise SpeechAPIError('speech_disabled', 503, 'Speech-to-text is turned off.')

    content_type = _base_content_type(request.headers.get('content-type'))
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise SpeechAPIError(
            'unsupported_audio_type', 415, 'That audio format is not supported.'
        )

    max_bytes = min(
        MAX_AUDIO_BYTES,
        int(state['max_audio_mb']) * MIB,
        settings_audio_ceiling(),
    )
    declared = request.headers.get('content-length')
    if declared is not None:
        try:
            if int(declared) > max_bytes:
                raise SpeechAPIError(
                    'audio_too_large', 413, 'The recording is too large.'
                )
        except ValueError:
            raise SpeechAPIError(
                'invalid_audio', 422, 'Invalid audio length.'
            ) from None

    user_id = str(user.id)
    # End the read transaction before a response that can stream for minutes.
    # The auth and settings reads are complete, and holding a pooled connection
    # for the whole transcription would starve ordinary chat requests. There are
    # no pending writes on this request-only session.
    await db.commit()

    lease = None
    upstream: SpeechStream | None = None
    handed_off = False
    try:
        lease = await speech_admission.acquire(user_id)
        audio = await _read_audio(request, max_bytes)
        if not _looks_like_audio(audio, content_type):
            raise SpeechAPIError(
                'invalid_audio', 422, 'The recording could not be read.'
            )
        upstream = await speech_client.open_stream(
            audio,
            content_type=content_type,
            queue_timeout_s=int(state['queue_timeout_s']),
            max_recording_seconds=int(state['max_recording_seconds']),
        )
        response = SpeechStreamingResponse(
            _stream_events(upstream, lease),
            lease=lease,
            upstream=upstream,
        )
        handed_off = True
        return response
    except SpeechClientError as exc:
        raise SpeechAPIError(exc.code, exc.status_code, exc.message) from None
    except SpeechAPIError:
        raise
    except Exception:
        logger.warning('speech request failed before streaming')
        raise SpeechAPIError(
            'speech_unavailable', 503, 'Speech is unavailable.'
        ) from None
    finally:
        if not handed_off:
            if lease is not None:
                speech_admission.release(lease)
            if upstream is not None:
                try:
                    await upstream.close()
                except Exception:
                    pass


def settings_audio_ceiling() -> int:
    from app.core.config import settings

    return max(1, min(5, int(settings.REVORA_SPEECH_MAX_AUDIO_MB))) * MIB
