'''Admin-owned speech settings stored in `platform_settings['speech']`.

There is deliberately no cache and no fail-open default: a missing row means
DISABLED, and an unreadable row is an error that keeps speech off. The write
path uses the row's version for optimistic concurrency, matching the other
platform settings. No audio or transcript is ever written here.
'''

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.platform import PlatformSetting

SPEECH_KEY = 'speech'
MIN_RECORDING_SECONDS = 5
MAX_RECORDING_SECONDS = 60
MIN_AUDIO_MB = 1
MAX_AUDIO_MB = 5
MIN_QUEUE_TIMEOUT_S = 5
MAX_QUEUE_TIMEOUT_S = 60


class SpeechVersionConflict(Exception):
    def __init__(self, expected: int, current: int) -> None:
        super().__init__('Speech settings changed; reload and retry.')
        self.expected = expected
        self.current = current


def _clamp(value: Any, low: int, high: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(high, parsed))


def default_state() -> dict[str, Any]:
    return {
        'enabled': False,
        'max_recording_seconds': _clamp(
            settings.REVORA_SPEECH_MAX_RECORDING_SECONDS,
            MIN_RECORDING_SECONDS,
            MAX_RECORDING_SECONDS,
            60,
        ),
        'max_audio_mb': _clamp(
            settings.REVORA_SPEECH_MAX_AUDIO_MB, MIN_AUDIO_MB, MAX_AUDIO_MB, 5
        ),
        'queue_timeout_s': _clamp(
            settings.REVORA_SPEECH_QUEUE_TIMEOUT_S,
            MIN_QUEUE_TIMEOUT_S,
            MAX_QUEUE_TIMEOUT_S,
            30,
        ),
        'changed_at': None,
        'changed_by': None,
        'version': 0,
    }


def normalize(raw: dict[str, Any] | None, version: int = 0) -> dict[str, Any]:
    value = default_state()
    if isinstance(raw, dict):
        # Only a real boolean may enable speech; a stray string such as
        # "false" must never fail open through Python's truthiness rules.
        value['enabled'] = raw.get('enabled') is True
        value['max_recording_seconds'] = _clamp(
            raw.get('max_recording_seconds'),
            MIN_RECORDING_SECONDS,
            min(MAX_RECORDING_SECONDS, settings.REVORA_SPEECH_MAX_RECORDING_SECONDS),
            value['max_recording_seconds'],
        )
        value['max_audio_mb'] = _clamp(
            raw.get('max_audio_mb'),
            MIN_AUDIO_MB,
            min(MAX_AUDIO_MB, settings.REVORA_SPEECH_MAX_AUDIO_MB),
            value['max_audio_mb'],
        )
        value['queue_timeout_s'] = _clamp(
            raw.get('queue_timeout_s'),
            MIN_QUEUE_TIMEOUT_S,
            MAX_QUEUE_TIMEOUT_S,
            value['queue_timeout_s'],
        )
        for key in ('changed_at', 'changed_by'):
            item = raw.get(key)
            if item is not None:
                value[key] = str(item)
    value['version'] = int(version or 0)
    return value


def effective_enabled(state: dict[str, Any]) -> bool:
    return bool(settings.REVORA_SPEECH_ENABLED) and bool(state.get('enabled'))


async def get_state(db: AsyncSession, *, force: bool = False) -> dict[str, Any]:
    '''Read the current state. `force` exists for call-site clarity: there is
    no cache to bypass, so an admin disable always takes effect immediately.'''
    del force
    row = (
        await db.execute(select(PlatformSetting).where(PlatformSetting.key == SPEECH_KEY))
    ).scalar_one_or_none()
    if row is None:
        return default_state()
    return normalize(row.value, row.version)


async def update_state(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID,
    enabled: bool,
    max_recording_seconds: int,
    max_audio_mb: int,
    queue_timeout_s: int,
    expected_version: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    # Lock the settings row so two admins cannot both pass the version check
    # and overwrite each other. SQLite ignores FOR UPDATE in tests.
    row = (
        await db.execute(
            select(PlatformSetting)
            .where(PlatformSetting.key == SPEECH_KEY)
            .with_for_update()
        )
    ).scalar_one_or_none()
    prior = normalize(row.value, row.version) if row is not None else default_state()
    current_version = prior['version']
    if int(expected_version) != int(current_version):
        raise SpeechVersionConflict(expected_version, current_version)

    new_version = current_version + 1
    value = {
        'enabled': bool(enabled),
        'max_recording_seconds': _clamp(
            max_recording_seconds,
            MIN_RECORDING_SECONDS,
            min(MAX_RECORDING_SECONDS, settings.REVORA_SPEECH_MAX_RECORDING_SECONDS),
            60,
        ),
        'max_audio_mb': _clamp(
            max_audio_mb,
            MIN_AUDIO_MB,
            min(MAX_AUDIO_MB, settings.REVORA_SPEECH_MAX_AUDIO_MB),
            5,
        ),
        'queue_timeout_s': _clamp(
            queue_timeout_s, MIN_QUEUE_TIMEOUT_S, MAX_QUEUE_TIMEOUT_S, 30
        ),
        'changed_at': datetime.now(UTC).isoformat(),
        'changed_by': str(actor_id),
        'version': new_version,
    }
    if row is None:
        row = PlatformSetting(
            key=SPEECH_KEY, value=value, updated_by=actor_id, version=new_version
        )
        db.add(row)
    else:
        row.value = value
        row.updated_by = actor_id
        row.version = new_version
    try:
        await db.flush()
    except IntegrityError:
        # Two admins created the first row at once; the unique key rejected
        # the loser. Report the same conflict as a stale version.
        await db.rollback()
        current = await get_state(db)
        raise SpeechVersionConflict(expected_version, int(current['version'])) from None
    return normalize(value, new_version), prior
