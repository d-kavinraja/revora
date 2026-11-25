import json
import wave
from io import BytesIO

from sqlalchemy import func, select

import app.api.v1.endpoints.admin.speech as admin_speech
import app.api.v1.endpoints.stt as stt_module
from app.core.config import settings
from app.models.platform import PlatformSetting
from app.services.speech_admission import SpeechAdmission
from app.services.speech_client import SpeechClientError
from app.services.speech_settings import SPEECH_KEY


def wav_bytes(seconds: float = 0.25) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, 'wb') as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16_000)
        handle.writeframes(b'\x00\x00' * int(seconds * 16_000))
    return buffer.getvalue()


class FakeStream:
    def __init__(self, events, error=None) -> None:
        self._events = events
        self._error = error
        self.closed = False

    async def events(self):
        if self._error is not None:
            raise self._error
        for event in self._events:
            yield event

    async def close(self) -> None:
        self.closed = True


class FakeClient:
    configured = True

    def __init__(self, stream=None, error=None) -> None:
        self.stream = stream or FakeStream(
            [
                {'type': 'queued'},
                {'type': 'processing'},
                {'type': 'result', 'text': 'hello there'},
            ]
        )
        self.error = error
        self.calls = []

    async def open_stream(self, audio, **kwargs):
        self.calls.append((audio, kwargs))
        if self.error is not None:
            raise self.error
        return self.stream

    async def health(self):
        return {
            'configured': True,
            'reachable': True,
            'ready': True,
            'active': 0,
            'queued': 0,
            'capacity': 4,
            'error': None,
        }


async def seed_speech(test_db, *, enabled: bool = True, version: int = 1):
    test_db.add(
        PlatformSetting(
            key=SPEECH_KEY,
            value={
                'enabled': enabled,
                'max_recording_seconds': 30,
                'max_audio_mb': 5,
                'queue_timeout_s': 20,
                'changed_at': None,
                'changed_by': None,
                'version': version,
            },
            version=version,
        )
    )
    await test_db.commit()


async def test_config_defaults_to_disabled(client, test_db, monkeypatch):
    monkeypatch.setattr(settings, 'REVORA_SPEECH_ENABLED', True)
    response = client.get('/api/v1/stt/config')
    assert response.status_code == 200
    assert response.json() == {
        'enabled': False,
        'max_recording_seconds': 60,
        'max_audio_mb': 5,
    }
    assert response.headers['cache-control'].startswith('no-store')


async def test_config_is_disabled_by_environment_kill_switch(client, monkeypatch):
    monkeypatch.setattr(settings, 'REVORA_SPEECH_ENABLED', False)
    response = client.get('/api/v1/stt/config')
    assert response.status_code == 200
    assert response.json()['enabled'] is False


async def test_transcribe_is_503_when_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, 'REVORA_SPEECH_ENABLED', True)
    response = client.post(
        '/api/v1/stt/transcribe',
        content=wav_bytes(),
        headers={'Content-Type': 'audio/wav'},
    )
    assert response.status_code == 503
    assert response.json()['code'] == 'speech_disabled'


async def test_transcribe_streams_events_and_releases_admission(
    client, test_db, monkeypatch
):
    monkeypatch.setattr(settings, 'REVORA_SPEECH_ENABLED', True)
    monkeypatch.setattr(stt_module, 'speech_admission', SpeechAdmission())
    fake = FakeClient()
    monkeypatch.setattr(stt_module, 'speech_client', fake)
    await seed_speech(test_db)
    response = client.post(
        '/api/v1/stt/transcribe',
        content=wav_bytes(),
        headers={'Content-Type': 'audio/wav'},
    )
    assert response.status_code == 200
    assert response.headers['cache-control'].startswith('no-store')
    lines = [json.loads(line) for line in response.text.splitlines() if line]
    assert lines[0] == {'type': 'queued'}
    assert lines[1] == {'type': 'processing'}
    assert lines[-1] == {'type': 'result', 'text': 'hello there'}
    assert fake.calls[0][1]['max_recording_seconds'] == 30
    assert stt_module.speech_admission._global == 0
    assert fake.stream.closed is True


async def test_unsupported_content_type_is_415(client, test_db, monkeypatch):
    monkeypatch.setattr(settings, 'REVORA_SPEECH_ENABLED', True)
    await seed_speech(test_db)
    response = client.post(
        '/api/v1/stt/transcribe',
        content=b'hello',
        headers={'Content-Type': 'text/plain'},
    )
    assert response.status_code == 415
    assert response.json()['code'] == 'unsupported_audio_type'


async def test_oversized_declared_body_is_413(client, test_db, monkeypatch):
    monkeypatch.setattr(settings, 'REVORA_SPEECH_ENABLED', True)
    await seed_speech(test_db)
    response = client.post(
        '/api/v1/stt/transcribe',
        content=b'x',
        headers={
            'Content-Type': 'audio/wav',
            'Content-Length': str(6 * 1024 * 1024),
        },
    )
    assert response.status_code == 413
    assert response.json()['code'] == 'audio_too_large'


async def test_invalid_audio_magic_is_rejected(client, test_db, monkeypatch):
    monkeypatch.setattr(settings, 'REVORA_SPEECH_ENABLED', True)
    fake = FakeClient()
    monkeypatch.setattr(stt_module, 'speech_client', fake)
    await seed_speech(test_db)
    response = client.post(
        '/api/v1/stt/transcribe',
        content=b'not a wav at all, really',
        headers={'Content-Type': 'audio/wav'},
    )
    assert response.status_code == 422
    assert response.json()['code'] == 'invalid_audio'
    assert stt_module.speech_admission._global == 0


async def test_upstream_queue_full_maps_to_429(client, test_db, monkeypatch):
    monkeypatch.setattr(settings, 'REVORA_SPEECH_ENABLED', True)
    monkeypatch.setattr(stt_module, 'speech_admission', SpeechAdmission())
    fake = FakeClient(
        error=SpeechClientError('speech_queue_full', 429, 'Speech is busy.')
    )
    monkeypatch.setattr(stt_module, 'speech_client', fake)
    await seed_speech(test_db)
    response = client.post(
        '/api/v1/stt/transcribe',
        content=wav_bytes(),
        headers={'Content-Type': 'audio/wav'},
    )
    assert response.status_code == 429
    assert response.json()['code'] == 'speech_queue_full'
    assert stt_module.speech_admission._global == 0


async def test_upstream_stream_error_is_forwarded(client, test_db, monkeypatch):
    monkeypatch.setattr(settings, 'REVORA_SPEECH_ENABLED', True)
    monkeypatch.setattr(stt_module, 'speech_admission', SpeechAdmission())
    fake = FakeClient(
        stream=FakeStream(
            [], error=SpeechClientError('speech_timeout', 504, 'Timed out.')
        )
    )
    monkeypatch.setattr(stt_module, 'speech_client', fake)
    await seed_speech(test_db)
    response = client.post(
        '/api/v1/stt/transcribe',
        content=wav_bytes(),
        headers={'Content-Type': 'audio/wav'},
    )
    assert response.status_code == 200
    lines = [json.loads(line) for line in response.text.splitlines() if line]
    assert lines[-1]['type'] == 'error'
    assert lines[-1]['code'] == 'speech_timeout'
    assert stt_module.speech_admission._global == 0


async def test_response_releases_lease_even_before_streaming_starts(monkeypatch) -> None:
    admission = SpeechAdmission()
    monkeypatch.setattr(stt_module, 'speech_admission', admission)
    lease = await admission.acquire('disconnect-user')
    upstream = FakeStream([])

    async def empty_stream():
        if False:
            yield ''

    response = stt_module.SpeechStreamingResponse(
        empty_stream(), lease=lease, upstream=upstream
    )
    scope = {
        'type': 'http',
        'asgi': {'version': '3.0'},
        'http_version': '1.1',
        'method': 'GET',
        'scheme': 'http',
        'path': '/',
        'raw_path': b'/',
        'query_string': b'',
        'headers': [],
        'client': ('127.0.0.1', 12345),
        'server': ('testserver', 80),
    }

    async def receive() -> dict[str, str]:
        return {'type': 'http.disconnect'}

    async def send(_message: dict[str, object]) -> None:
        return None

    await response(scope, receive, send)
    assert admission._global == 0
    assert upstream.closed is True


async def test_config_does_not_write_any_rows(client, test_db, monkeypatch):
    monkeypatch.setattr(settings, 'REVORA_SPEECH_ENABLED', True)
    before = (
        await test_db.execute(select(func.count()).select_from(PlatformSetting))
    ).scalar_one()
    client.get('/api/v1/stt/config')
    after = (
        await test_db.execute(select(func.count()).select_from(PlatformSetting))
    ).scalar_one()
    assert before == after


async def test_admin_speech_status_and_update(admin_client, test_db, monkeypatch):
    monkeypatch.setattr(settings, 'REVORA_SPEECH_ENABLED', True)
    monkeypatch.setattr(admin_speech, 'speech_client', FakeClient())
    response = admin_client.get('/api/v1/admin/hosted-ollama/speech')
    assert response.status_code == 200
    body = response.json()
    assert body['enabled'] is False
    assert body['environment_enabled'] is True
    assert body['engine']['max_concurrent_inferences'] == 1
    assert 'base_url' not in response.text.lower()

    response = admin_client.put(
        '/api/v1/admin/hosted-ollama/speech',
        json={
            'enabled': True,
            'max_recording_seconds': 45,
            'max_audio_mb': 4,
            'queue_timeout_s': 20,
            'version': 0,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body['enabled'] is True
    assert body['max_recording_seconds'] == 45
    assert body['version'] == 1


async def test_admin_update_rejects_stale_version(admin_client, test_db, monkeypatch):
    monkeypatch.setattr(settings, 'REVORA_SPEECH_ENABLED', True)
    monkeypatch.setattr(admin_speech, 'speech_client', FakeClient())
    await seed_speech(test_db, version=2)
    response = admin_client.put(
        '/api/v1/admin/hosted-ollama/speech',
        json={'enabled': False, 'version': 1},
    )
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'version_conflict'


async def test_admin_enable_requires_configuration(admin_client, monkeypatch):
    monkeypatch.setattr(settings, 'REVORA_SPEECH_ENABLED', True)
    fake = FakeClient()
    fake.configured = False
    monkeypatch.setattr(admin_speech, 'speech_client', fake)
    response = admin_client.put(
        '/api/v1/admin/hosted-ollama/speech',
        json={'enabled': True, 'version': 0},
    )
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'speech_not_configured'


async def test_admin_speech_requires_admin(anon_client):
    response = anon_client.get('/api/v1/admin/hosted-ollama/speech')
    assert response.status_code in {401, 403}
