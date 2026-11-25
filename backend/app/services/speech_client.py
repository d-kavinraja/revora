'''Server-side client for the private Whisper service.

The backend never loads a model, never queues inference itself, never writes
audio or transcripts anywhere, and never retries. This client is one hop to
the service that owns the single global inference slot.
'''

from __future__ import annotations

import ipaddress
import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core.config import settings

from .speech_errors import SpeechClientError

MAX_EVENT_BYTES = 64 * 1024
MAX_ERROR_BODY_BYTES = 8 * 1024
MAX_TRANSCRIPT_CHARS = 20_000
SERVICE_TOKEN_HEADER = 'authorization'

_ALLOWED_SERVICE_CODES = {
    'unauthorized',
    'speech_not_ready',
    'speech_queue_full',
    'speech_queue_timeout',
    'speech_timeout',
    'speech_cancelled',
    'invalid_audio',
    'audio_too_long',
    'audio_too_large',
    'unsupported_audio_type',
    'no_speech',
    'speech_upstream_error',
}


def _safe_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(high, parsed))


def _safe_host(host: str | None) -> str:
    if not host:
        return ''
    lowered = host.strip('[]').lower()
    if lowered == 'metadata.google.internal' or lowered.endswith('.internal'):
        return ''
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        return lowered
    if address.is_link_local or address.is_multicast or address.is_unspecified:
        return ''
    return lowered


class SpeechServiceClient:
    def __init__(self) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        if not self.settings.REVORA_SPEECH_ENABLED:
            return False
        if not (self.settings.REVORA_SPEECH_BASE_URL or '').strip():
            return False
        if not (self.settings.REVORA_SPEECH_TOKEN or '').strip():
            return False
        try:
            self._base_url()
        except SpeechClientError:
            return False
        return True

    def _base_url(self) -> str:
        raw = (self.settings.REVORA_SPEECH_BASE_URL or '').strip()
        if not raw:
            raise SpeechClientError(
                'speech_unavailable', 503, 'Speech is not configured.'
            )
        parsed = urlsplit(raw)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
            raise SpeechClientError(
                'speech_unavailable', 503, 'Speech is not configured.'
            )
        if parsed.username or parsed.password:
            raise SpeechClientError(
                'speech_unavailable', 503, 'Speech is not configured.'
            )
        if parsed.path not in {'', '/'} or parsed.query or parsed.fragment:
            raise SpeechClientError(
                'speech_unavailable', 503, 'Speech is not configured.'
            )
        host = _safe_host(parsed.hostname)
        loopback = host in {'localhost', '127.0.0.1', '::1'}
        if not host or (parsed.scheme == 'http' and not loopback):
            raise SpeechClientError(
                'speech_unavailable', 503, 'Speech is not configured.'
            )
        try:
            port = parsed.port
        except ValueError as exc:
            raise SpeechClientError(
                'speech_unavailable', 503, 'Speech is not configured.'
            ) from exc
        netloc = f'[{host}]' if ':' in host else host
        if port is not None:
            netloc = f'{netloc}:{port}'
        return f'{parsed.scheme}://{netloc}'

    def endpoint(self, path: str) -> str:
        base = self._base_url()
        # Never put the service credential in the URL: query strings are the
        # first thing a proxy or gateway access log records.
        return f'{base}/{path.lstrip("/")}'

    def _headers(self, *, content_type: str | None = None) -> dict[str, str]:
        headers = {
            'Authorization': f'Bearer {(self.settings.REVORA_SPEECH_TOKEN or "").strip()}',
            'Accept': 'application/x-ndjson',
        }
        if content_type:
            headers['Content-Type'] = content_type
        return headers

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=self.settings.REVORA_SPEECH_CONNECT_TIMEOUT_S,
            read=self.settings.REVORA_SPEECH_READ_TIMEOUT_S,
            write=self.settings.REVORA_SPEECH_WRITE_TIMEOUT_S,
            pool=self.settings.REVORA_SPEECH_CONNECT_TIMEOUT_S,
        )

    async def health(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            'configured': self.configured,
            'reachable': False,
            'ready': False,
            'state': 'unavailable',
            'active': 0,
            'queued': 0,
            'capacity': 4,
            'error': None,
        }
        if not self.settings.REVORA_SPEECH_ENABLED:
            result['state'] = 'disabled'
            result['error'] = 'Speech is disabled by the backend environment.'
            return result
        if not (self.settings.REVORA_SPEECH_BASE_URL or '').strip() or not (
            self.settings.REVORA_SPEECH_TOKEN or ''
        ).strip():
            result['state'] = 'configuration_error'
            result['error'] = 'Speech service is not configured.'
            return result
        if not self.configured:
            result['state'] = 'configuration_error'
            result['error'] = 'Speech service configuration is invalid.'
            return result
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=self.settings.REVORA_SPEECH_CONNECT_TIMEOUT_S,
                    read=self.settings.REVORA_SPEECH_CONNECT_TIMEOUT_S,
                    write=self.settings.REVORA_SPEECH_CONNECT_TIMEOUT_S,
                    pool=self.settings.REVORA_SPEECH_CONNECT_TIMEOUT_S,
                ),
                follow_redirects=False,
            ) as client:
                response = await client.get(
                    self.endpoint('/health'), headers=self._headers()
                )
        except httpx.ConnectTimeout:
            result['state'] = 'unavailable'
            result['error'] = 'The private speech tunnel did not respond before the health-check timeout.'
            return result
        except httpx.ConnectError:
            result['state'] = 'unavailable'
            result['error'] = 'The private speech tunnel refused the health-check connection.'
            return result
        except httpx.TimeoutException:
            result['state'] = 'unavailable'
            result['error'] = 'The speech service health check timed out.'
            return result
        except httpx.HTTPError:
            result['state'] = 'unavailable'
            result['error'] = 'The private speech service could not be reached.'
            return result
        except Exception:
            result['state'] = 'unavailable'
            result['error'] = 'The speech service health check failed.'
            return result
        if response.status_code == 401:
            result['state'] = 'authentication_error'
            result['error'] = 'The speech service rejected the health check (authentication failed).'
            return result
        if response.status_code != 200:
            result['state'] = 'recovering' if response.status_code >= 500 else 'error'
            result['error'] = f'The speech service returned HTTP {response.status_code} for its health check.'
            return result
        try:
            payload = response.json()
        except ValueError:
            result['state'] = 'error'
            result['error'] = 'Speech service returned an invalid health response.'
            return result
        if not isinstance(payload, dict):
            result['state'] = 'error'
            result['error'] = 'Speech service returned an invalid health response.'
            return result
        ready = bool(payload.get('ready'))
        result.update(
            {
                'reachable': True,
                'ready': ready,
                'state': 'ready' if ready else 'recovering',
                'active': _safe_int(payload.get('active'), 0, 0, 1),
                'queued': _safe_int(payload.get('queued'), 0, 0, 16),
                'capacity': _safe_int(payload.get('capacity'), 4, 1, 16),
                'error': None if ready else 'The speech model is not ready.',
            }
        )
        return result

    async def open_stream(
        self,
        audio: bytes,
        *,
        content_type: str,
        queue_timeout_s: int,
        max_recording_seconds: int,
    ) -> 'SpeechStream':
        if not self.configured:
            raise SpeechClientError(
                'speech_unavailable', 503, 'Speech is not configured.'
            )
        if not audio:
            raise SpeechClientError('invalid_audio', 422, 'The recording was empty.')
        headers = self._headers(content_type=content_type)
        headers['X-Max-Recording-Seconds'] = str(max_recording_seconds)
        headers['X-Queue-Timeout-Seconds'] = str(queue_timeout_s)
        client = httpx.AsyncClient(
            timeout=self._timeout(),
            follow_redirects=False,
        )
        try:
            # Build inside the cleanup boundary: an invalid configured token or
            # URL must not leak the client (and must still fail closed).
            request = client.build_request(
                'POST', self.endpoint('/transcribe'), content=audio, headers=headers
            )
            response = await client.send(request, stream=True)
        except (httpx.TimeoutException, httpx.TransportError):
            await client.aclose()
            raise SpeechClientError(
                'speech_unavailable', 503, 'Speech service is unreachable.'
            )
        except Exception:
            await client.aclose()
            raise SpeechClientError(
                'speech_unavailable', 503, 'Speech service is unreachable.'
            )
        if response.status_code != 200:
            error = await _upstream_error(response)
            await response.aclose()
            await client.aclose()
            raise error
        return SpeechStream(client, response)


async def _upstream_error(response: httpx.Response) -> SpeechClientError:
    code = 'speech_upstream_error'
    message = 'Speech service rejected the request.'
    try:
        raw = bytearray()
        async for chunk in response.aiter_bytes():
            raw.extend(chunk)
            if len(raw) > MAX_ERROR_BODY_BYTES:
                break
        if len(raw) <= MAX_ERROR_BODY_BYTES:
            payload = json.loads(bytes(raw).decode('utf-8'))
            if isinstance(payload, dict):
                candidate = str(payload.get('code') or '')
                if candidate in _ALLOWED_SERVICE_CODES:
                    code = candidate
                text = str(payload.get('message') or '').strip()
                if text:
                    message = text[:300]
    except Exception:
        pass
    status = response.status_code
    if code == 'audio_too_large':
        return SpeechClientError('audio_too_large', 413, 'The recording is too large.')
    if code == 'unsupported_audio_type':
        return SpeechClientError(
            'unsupported_audio_type', 415, 'That audio format is not supported.'
        )
    if code in {'invalid_audio', 'audio_too_long', 'no_speech'}:
        return SpeechClientError(code, 422, message)
    if code in {'speech_queue_full', 'speech_queue_timeout'}:
        return SpeechClientError(code, 429, message)
    if code == 'speech_timeout':
        return SpeechClientError('speech_timeout', 504, 'Speech processing timed out.')
    if code in {'speech_not_ready', 'speech_cancelled'}:
        return SpeechClientError(
            'speech_unavailable', 503, 'Speech service is not ready.'
        )
    if status == 401:
        return SpeechClientError(
            'speech_unavailable', 503, 'Speech service is unavailable.'
        )
    if status == 504:
        return SpeechClientError('speech_timeout', 504, 'Speech processing timed out.')
    if status == 503:
        return SpeechClientError(
            'speech_unavailable', 503, 'Speech service is not ready.'
        )
    return SpeechClientError(
        'speech_upstream_error', 502, 'Speech service failed to process the request.'
    )


class SpeechStream:
    '''Bounded NDJSON reader over one open upstream response.'''

    def __init__(self, client: httpx.AsyncClient, response: httpx.Response) -> None:
        self._client = client
        self._response = response
        self._closed = False

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._response.aclose()
        finally:
            await self._client.aclose()

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        buffer = bytearray()
        async for chunk in self._response.aiter_bytes():
            if not chunk:
                continue
            buffer.extend(chunk)
            if len(buffer) > MAX_EVENT_BYTES and b'\n' not in buffer:
                raise SpeechClientError(
                    'speech_upstream_error', 502, 'Speech service returned an invalid stream.'
                )
            while True:
                index = buffer.find(b'\n')
                if index < 0:
                    break
                line = bytes(buffer[:index])
                del buffer[: index + 1]
                event = _parse_event(line)
                if event is not None:
                    yield event
        if buffer.strip():
            event = _parse_event(bytes(buffer))
            if event is not None:
                yield event


def _parse_event(line: bytes) -> dict[str, Any] | None:
    if not line.strip():
        return None
    if len(line) > MAX_EVENT_BYTES:
        raise SpeechClientError(
            'speech_upstream_error', 502, 'Speech service returned an invalid stream.'
        )
    try:
        payload = json.loads(line.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        raise SpeechClientError(
            'speech_upstream_error', 502, 'Speech service returned an invalid stream.'
        ) from None
    if not isinstance(payload, dict):
        raise SpeechClientError(
            'speech_upstream_error', 502, 'Speech service returned an invalid stream.'
        )
    kind = payload.get('type')
    if not isinstance(kind, str):
        raise SpeechClientError(
            'speech_upstream_error', 502, 'Speech service returned an invalid stream.'
        )
    if kind in {'queued', 'processing'}:
        return {'type': kind}
    if kind == 'result':
        text = payload.get('text')
        if not isinstance(text, str):
            raise SpeechClientError(
                'speech_upstream_error', 502, 'Speech service returned an invalid result.'
            )
        text = text.strip()
        if not text or len(text) > MAX_TRANSCRIPT_CHARS:
            raise SpeechClientError(
                'speech_upstream_error', 502, 'Speech service returned an invalid result.'
            )
        return {'type': 'result', 'text': text}
    if kind == 'error':
        code = str(payload.get('code') or 'speech_upstream_error')[:64]
        message = str(payload.get('message') or 'Speech failed.')[:300]
        return {'type': 'error', 'code': code, 'message': message}
    raise SpeechClientError(
        'speech_upstream_error', 502, 'Speech service returned an invalid stream.'
    )


speech_client = SpeechServiceClient()
