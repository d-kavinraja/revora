import asyncio
import json
import uuid

import httpx
import pytest
from starlette.requests import Request

from app.core.config import Settings, settings
from app.core.deps import get_current_user_readonly
from app.services.speech_admission import SpeechAdmission
from app.services.speech_client import SpeechClientError, SpeechStream, _upstream_error
from app.services.speech_errors import SpeechAPIError
from app.services.speech_settings import (
    SpeechVersionConflict,
    default_state,
    effective_enabled,
    normalize,
    update_state,
)


def test_environment_kill_switch_ships_off():
    field = Settings.model_fields['REVORA_SPEECH_ENABLED']
    assert field.default is False


def test_default_state_is_disabled_and_clamped_to_operator_ceilings(monkeypatch):
    monkeypatch.setattr(settings, 'REVORA_SPEECH_MAX_RECORDING_SECONDS', 10)
    monkeypatch.setattr(settings, 'REVORA_SPEECH_MAX_AUDIO_MB', 2)
    state = default_state()
    assert state['enabled'] is False
    assert state['max_recording_seconds'] == 10
    assert state['max_audio_mb'] == 2
    assert state['queue_timeout_s'] == 30


def test_normalize_rejects_non_boolean_enable_and_clamps_values():
    state = normalize(
        {
            'enabled': 'false',
            'max_recording_seconds': 999,
            'max_audio_mb': 0,
            'queue_timeout_s': -4,
            'changed_by': uuid.uuid4(),
        },
        version=7,
    )
    assert state['enabled'] is False
    assert state['max_recording_seconds'] == 60
    assert state['max_audio_mb'] == 1
    assert state['queue_timeout_s'] == 5
    assert state['version'] == 7
    assert normalize({'enabled': True})['enabled'] is True


def test_normalize_honors_lowered_operator_ceilings(monkeypatch):
    monkeypatch.setattr(settings, 'REVORA_SPEECH_MAX_RECORDING_SECONDS', 12)
    monkeypatch.setattr(settings, 'REVORA_SPEECH_MAX_AUDIO_MB', 2)
    state = normalize(
        {
            'enabled': True,
            'max_recording_seconds': 60,
            'max_audio_mb': 5,
            'queue_timeout_s': 30,
        }
    )
    assert state['max_recording_seconds'] == 12
    assert state['max_audio_mb'] == 2


def test_effective_enable_requires_both_switches(monkeypatch):
    state = {'enabled': True}
    monkeypatch.setattr(settings, 'REVORA_SPEECH_ENABLED', True)
    assert effective_enabled(state) is True
    monkeypatch.setattr(settings, 'REVORA_SPEECH_ENABLED', False)
    assert effective_enabled(state) is False


async def test_update_state_uses_version_and_operator_ceiling(test_db, monkeypatch):
    monkeypatch.setattr(settings, 'REVORA_SPEECH_MAX_RECORDING_SECONDS', 20)
    actor = uuid.uuid4()
    state, prior = await update_state(
        test_db,
        actor_id=actor,
        enabled=True,
        max_recording_seconds=60,
        max_audio_mb=5,
        queue_timeout_s=30,
        expected_version=0,
    )
    assert prior['version'] == 0
    assert state['version'] == 1
    assert state['max_recording_seconds'] == 20
    assert state['changed_by'] == str(actor)
    with pytest.raises(SpeechVersionConflict):
        await update_state(
            test_db,
            actor_id=actor,
            enabled=False,
            max_recording_seconds=30,
            max_audio_mb=5,
            queue_timeout_s=30,
            expected_version=0,
        )


async def test_admission_allows_one_in_flight_request_per_user():
    admission = SpeechAdmission(rate_per_minute=6, capacity=4)
    lease = await admission.acquire('user-a')
    with pytest.raises(SpeechAPIError) as caught:
        await admission.acquire('user-a')
    assert caught.value.code == 'speech_busy'
    admission.release(lease)
    second = await admission.acquire('user-a')
    admission.release(second)
    assert admission._global == 0


async def test_admission_rate_limit_and_global_capacity_are_bounded():
    rate = SpeechAdmission(rate_per_minute=2, capacity=4)
    for _ in range(2):
        lease = await rate.acquire('user-a')
        rate.release(lease)
    with pytest.raises(SpeechAPIError) as limited:
        await rate.acquire('user-a')
    assert limited.value.code == 'speech_rate_limited'

    capacity = SpeechAdmission(rate_per_minute=6, capacity=1)
    lease = await capacity.acquire('user-a')
    with pytest.raises(SpeechAPIError) as busy:
        await capacity.acquire('user-b')
    assert busy.value.code == 'speech_busy'
    capacity.release(lease)


async def test_admission_prunes_tracked_user_windows():
    admission = SpeechAdmission(rate_per_minute=6, capacity=4, max_tracked_users=2)
    for name in ('a', 'b', 'c', 'd'):
        lease = await admission.acquire(name)
        admission.release(lease)
    assert len(admission._windows) <= 2
    assert admission._global == 0


def test_client_url_is_loopback_http_or_https_without_credentials(monkeypatch):
    from app.services.speech_client import SpeechServiceClient

    monkeypatch.setattr(settings, 'REVORA_SPEECH_ENABLED', True)
    monkeypatch.setattr(settings, 'REVORA_SPEECH_TOKEN', 'secret-token')
    client = SpeechServiceClient()
    for allowed in (
        'https://speech.example.com',
        'http://127.0.0.1:8010',
        'http://[::1]:8010',
        'http://localhost:8010',
    ):
        monkeypatch.setattr(settings, 'REVORA_SPEECH_BASE_URL', allowed)
        assert client.configured is True
        assert client._base_url() == allowed.rstrip('/')
    for rejected in (
        'http://speech.example.com',
        'https://user:pass@speech.example.com',
        'https://speech.example.com/path',
        'https://speech.example.com?token=x',
        'https://169.254.169.254',
        'https://metadata.google.internal',
        'ftp://speech.example.com',
    ):
        monkeypatch.setattr(settings, 'REVORA_SPEECH_BASE_URL', rejected)
        assert client.configured is False
        with pytest.raises(SpeechClientError):
            client._base_url()


async def test_client_stream_parses_fragmented_ndjson_and_bounds_events():
    class FakeResponse:
        def __init__(self, chunks):
            self.chunks = chunks

        async def aiter_bytes(self):
            for chunk in self.chunks:
                yield chunk

        async def aclose(self):
            pass

    class FakeHTTP:
        async def aclose(self):
            pass

    stream = SpeechStream(
        FakeHTTP(),
        FakeResponse([b'{"type":"que', b'ued"}\n{"type":"result","text":" hi "}']),
    )
    events = [event async for event in stream.events()]
    assert events == [{'type': 'queued'}, {'type': 'result', 'text': 'hi'}]
    await stream.close()

    oversized = SpeechStream(FakeHTTP(), FakeResponse([b'x' * (64 * 1024 + 1)]))
    with pytest.raises(SpeechClientError):
        [event async for event in oversized.events()]
    await oversized.close()

    malformed = SpeechStream(FakeHTTP(), FakeResponse([b'not-json\n']))
    with pytest.raises(SpeechClientError):
        [event async for event in malformed.events()]
    await malformed.close()


async def test_upstream_error_mapping_is_safe_and_bounded():
    response = httpx.Response(
        429,
        json={'code': 'speech_queue_full', 'message': 'busy' * 200},
    )
    error = await _upstream_error(response)
    assert error.code == 'speech_queue_full'
    assert error.status_code == 429
    assert len(error.message) <= 300

    unknown = httpx.Response(500, json={'code': 'stacktrace', 'message': 'secret'})
    mapped = await _upstream_error(unknown)
    assert mapped.code == 'speech_upstream_error'
    assert mapped.status_code == 502


async def test_readonly_dependency_does_not_touch_activity(test_db, mock_user, user_auth_token, monkeypatch):
    mock_user.last_active_at = None
    await test_db.commit()

    async def forbidden_commit():
        raise AssertionError('read-only auth must not commit')

    monkeypatch.setattr(test_db, 'commit', forbidden_commit)
    request = Request(
        {
            'type': 'http',
            'method': 'GET',
            'path': '/api/v1/stt/config',
            'headers': [],
            'query_string': b'',
            'server': ('test', 80),
            'client': ('test', 1),
            'scheme': 'http',
        }
    )
    user = await get_current_user_readonly(request, user_auth_token, test_db)
    assert user.id == mock_user.id
    assert user.last_active_at is None


async def test_transcribe_writes_no_rows_and_logs_no_transcript(
    client, test_db, monkeypatch, caplog
):
    from sqlalchemy import func, select

    import app.api.v1.endpoints.stt as stt_module
    from app.db.base import Base
    from app.models.platform import PlatformSetting
    from app.services.speech_settings import SPEECH_KEY

    class FakeStream:
        async def events(self):
            yield {'type': 'result', 'text': 'private transcript sentinel'}

        async def close(self):
            pass

    class FakeClient:
        configured = True

        async def open_stream(self, audio, **kwargs):
            return FakeStream()

    monkeypatch.setattr(settings, 'REVORA_SPEECH_ENABLED', True)
    monkeypatch.setattr(stt_module, 'speech_admission', SpeechAdmission())
    monkeypatch.setattr(stt_module, 'speech_client', FakeClient())
    test_db.add(
        PlatformSetting(
            key=SPEECH_KEY,
            value={'enabled': True, 'max_recording_seconds': 30, 'max_audio_mb': 5, 'queue_timeout_s': 20, 'version': 1},
            version=1,
        )
    )
    await test_db.commit()

    async def counts():
        result = {}
        for table in Base.metadata.sorted_tables:
            result[table.name] = (
                await test_db.execute(select(func.count()).select_from(table))
            ).scalar_one()
        return result

    before = await counts()
    caplog.set_level('DEBUG')
    caplog.clear()
    response = client.post(
        '/api/v1/stt/transcribe',
        content=b'RIFF' + b'\x00' * 4 + b'WAVE' + b'\x00' * 32,
        headers={'Content-Type': 'audio/wav'},
    )
    assert response.status_code == 200
    assert 'private transcript sentinel' not in caplog.text
    after = await counts()
    assert after == before


async def test_config_fails_closed_when_settings_are_unreadable(client, monkeypatch):
    import app.api.v1.endpoints.stt as stt_module

    async def broken(_db, force=False):
        raise RuntimeError('database unavailable')

    monkeypatch.setattr(stt_module.speech_settings, 'get_state', broken)
    response = client.get('/api/v1/stt/config')
    assert response.status_code == 503
    assert response.json()['code'] == 'speech_unavailable'


async def test_admin_update_writes_audit_without_service_secrets(
    admin_client, test_db, monkeypatch
):
    from sqlalchemy import select

    import app.api.v1.endpoints.admin.speech as admin_speech
    from app.models.audit import AuditLog

    class FakeClient:
        configured = True

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

    secret = 'service-token-that-must-never-leak'
    monkeypatch.setattr(settings, 'REVORA_SPEECH_ENABLED', True)
    monkeypatch.setattr(settings, 'REVORA_SPEECH_BASE_URL', 'https://speech.example.com')
    monkeypatch.setattr(settings, 'REVORA_SPEECH_TOKEN', secret)
    monkeypatch.setattr(admin_speech, 'speech_client', FakeClient())

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
    assert secret not in response.text
    assert 'speech.example.com' not in response.text
    assert 'base_url' not in response.text.lower()

    row = (
        await test_db.execute(
            select(AuditLog).where(AuditLog.action == 'admin.speech_enabled')
        )
    ).scalar_one()
    assert row.details['enabled'] is True
    assert row.details['version'] == 1
    assert secret not in json.dumps(row.details)
    assert 'speech.example.com' not in json.dumps(row.details)
async def test_backend_upload_timeout_fails_closed(monkeypatch):
    import app.api.v1.endpoints.stt as stt_module

    class SlowRequest:
        async def stream(self):
            yield b'RIFF' + b'\x00' * 4 + b'WAVE' + b'\x00' * 32
            await asyncio.sleep(1)

    monkeypatch.setattr(stt_module, 'UPLOAD_TIMEOUT_S', 0.01)
    with pytest.raises(SpeechAPIError) as caught:
        await stt_module._read_audio(SlowRequest(), 100)
    assert caught.value.code == 'speech_timeout'
    assert caught.value.status_code == 408
async def test_stream_close_failure_still_releases_admission(monkeypatch):
    import app.api.v1.endpoints.stt as stt_module

    class FakeUpstream:
        async def events(self):
            yield {'type': 'result', 'text': 'ok'}

        async def close(self):
            raise RuntimeError('socket already gone')

    class FakeLease:
        user_id = 'user-a'
        released = False

    class FakeAdmission:
        def __init__(self):
            self.leases = []

        def release(self, lease):
            lease.released = True
            self.leases.append(lease)

    admission = FakeAdmission()
    lease = FakeLease()
    monkeypatch.setattr(stt_module, 'speech_admission', admission)
    lines = [line async for line in stt_module._stream_events(FakeUpstream(), lease)]
    assert len(lines) == 1
    assert lease.released is True
    assert admission.leases == [lease]


def _speech_health_client(monkeypatch, outcomes):
    import app.services.speech_client as speech_client_module
    from app.services.speech_client import SpeechServiceClient

    monkeypatch.setattr(settings, 'REVORA_SPEECH_ENABLED', True)
    monkeypatch.setattr(settings, 'REVORA_SPEECH_BASE_URL', 'http://127.0.0.1:18010')
    monkeypatch.setattr(settings, 'REVORA_SPEECH_TOKEN', 'health-secret-token')

    class FakeResponse:
        def __init__(self, status_code=200, payload=None, invalid_json=False):
            self.status_code = status_code
            self._payload = payload
            self._invalid_json = invalid_json

        def json(self):
            if self._invalid_json:
                raise ValueError('invalid json')
            return self._payload

    class FakeAsyncClient:
        def __init__(self, outcome):
            self.outcome = outcome

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, *_args, **_kwargs):
            if isinstance(self.outcome, Exception):
                raise self.outcome
            return self.outcome

    class Factory:
        def __init__(self):
            self.outcomes = list(outcomes)

        def __call__(self, **_kwargs):
            return FakeAsyncClient(self.outcomes.pop(0))

    monkeypatch.setattr(speech_client_module.httpx, 'AsyncClient', Factory())
    return SpeechServiceClient()


async def test_health_connection_refused_is_classified_without_secrets(monkeypatch):
    client = _speech_health_client(
        monkeypatch, [httpx.ConnectError('connection refused')]
    )
    result = await client.health()
    assert result['configured'] is True
    assert result['reachable'] is False
    assert result['ready'] is False
    assert 'refused' in result['error'].lower()
    rendered = json.dumps(result)
    assert 'health-secret-token' not in rendered
    assert '127.0.0.1' not in rendered


async def test_health_connect_timeout_is_classified(monkeypatch):
    client = _speech_health_client(
        monkeypatch, [httpx.ConnectTimeout('connect timed out')]
    )
    result = await client.health()
    assert result['reachable'] is False
    assert 'timeout' in result['error'].lower()


async def test_health_read_timeout_is_classified(monkeypatch):
    client = _speech_health_client(
        monkeypatch, [httpx.ReadTimeout('read timed out')]
    )
    result = await client.health()
    assert result['reachable'] is False
    assert 'timed out' in result['error'].lower()


async def test_health_authentication_failure_is_classified(monkeypatch):
    client = _speech_health_client(monkeypatch, [httpx.Response(401)])
    result = await client.health()
    assert result['reachable'] is False
    assert 'authentication' in result['error'].lower()


async def test_health_non_200_is_classified_without_body(monkeypatch):
    client = _speech_health_client(monkeypatch, [httpx.Response(503)])
    result = await client.health()
    assert result['reachable'] is False
    assert '503' in result['error']


async def test_health_invalid_json_is_classified(monkeypatch):
    client = _speech_health_client(
        monkeypatch, [httpx.Response(200, text='not json')]
    )
    result = await client.health()
    assert result['reachable'] is False
    assert 'invalid' in result['error'].lower()


async def test_health_ready_response_updates_bounded_fields(monkeypatch):
    response = httpx.Response(
        200,
        json={'ready': True, 'active': 99, 'queued': 99, 'capacity': 99},
    )
    client = _speech_health_client(monkeypatch, [response])
    result = await client.health()
    assert result == {
        'configured': True,
        'reachable': True,
        'ready': True,
        'state': 'ready',
        'active': 1,
        'queued': 16,
        'capacity': 16,
        'error': None,
    }


async def test_health_not_ready_is_distinct_from_unreachable(monkeypatch):
    response = httpx.Response(200, json={'ready': False})
    client = _speech_health_client(monkeypatch, [response])
    result = await client.health()
    assert result['reachable'] is True
    assert result['ready'] is False
    assert result['error'] == 'The speech model is not ready.'


async def test_health_recovers_after_tunnel_reconnect(monkeypatch):
    response = httpx.Response(200, json={'ready': True})
    client = _speech_health_client(
        monkeypatch, [httpx.ConnectError('connection refused'), response]
    )
    failed = await client.health()
    assert failed['reachable'] is False
    recovered = await client.health()
    assert recovered['reachable'] is True
    assert recovered['ready'] is True
    assert recovered['error'] is None


async def test_health_invalid_configuration_is_not_reported_as_unreachable(monkeypatch):
    from app.services.speech_client import SpeechServiceClient

    monkeypatch.setattr(settings, 'REVORA_SPEECH_ENABLED', True)
    monkeypatch.setattr(settings, 'REVORA_SPEECH_BASE_URL', 'http://speech.example.com')
    monkeypatch.setattr(settings, 'REVORA_SPEECH_TOKEN', 'health-secret-token')
    result = await SpeechServiceClient().health()
    assert result['reachable'] is False
    assert 'invalid' in result['error'].lower()
    assert 'health-secret-token' not in json.dumps(result)
