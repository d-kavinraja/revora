'''Per-worker speech admission: one in-flight request per user, a per-user
rate window, and a small global request cap. The authoritative single
inference slot still lives inside the Whisper service; this only protects
the backend from unbounded uploads. All state is process memory.'''

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from app.core.config import settings

from .speech_errors import SpeechAPIError


@dataclass(eq=False)
class AdmissionLease:
    user_id: str
    released: bool = field(default=False, init=False)


class SpeechAdmission:
    def __init__(
        self,
        *,
        rate_per_minute: int = 6,
        capacity: int = 4,
        max_tracked_users: int = 4096,
    ) -> None:
        self.rate_per_minute = max(1, int(rate_per_minute))
        self.capacity = max(1, int(capacity))
        self.max_tracked_users = max(1, int(max_tracked_users))
        self._lock = asyncio.Lock()
        self._in_flight: set[str] = set()
        self._windows: dict[str, list[float]] = {}
        self._global = 0

    def _prune_windows(self, now: float) -> None:
        if len(self._windows) <= self.max_tracked_users:
            return
        for tracked, stamps in list(self._windows.items()):
            recent = [stamp for stamp in stamps if now - stamp < 60.0]
            if recent:
                self._windows[tracked] = recent
            else:
                del self._windows[tracked]
        overflow = len(self._windows) - self.max_tracked_users
        if overflow <= 0:
            return
        oldest = sorted(
            self._windows.items(),
            key=lambda item: item[1][-1] if item[1] else 0.0,
        )[:overflow]
        for tracked, _stamps in oldest:
            del self._windows[tracked]

    async def acquire(self, user_id: str) -> AdmissionLease:
        async with self._lock:
            now = time.monotonic()
            self._prune_windows(now)
            if (
                user_id not in self._windows
                and len(self._windows) >= self.max_tracked_users
            ):
                oldest = min(
                    self._windows,
                    key=lambda tracked: self._windows[tracked][-1]
                    if self._windows[tracked]
                    else 0.0,
                )
                del self._windows[oldest]
            recent = [
                stamp
                for stamp in self._windows.get(user_id, [])
                if now - stamp < 60.0
            ]
            self._windows[user_id] = recent
            if user_id in self._in_flight:
                raise SpeechAPIError(
                    'speech_busy', 429, 'A recording is already being transcribed.'
                )
            if len(recent) >= self.rate_per_minute:
                raise SpeechAPIError(
                    'speech_rate_limited', 429, 'Too many speech requests. Try again shortly.'
                )
            if self._global >= self.capacity:
                raise SpeechAPIError(
                    'speech_busy', 429, 'Speech is busy. Try again shortly.'
                )
            recent.append(now)
            self._in_flight.add(user_id)
            self._global += 1
            return AdmissionLease(user_id)

    def release(self, lease: AdmissionLease) -> None:
        # Deliberately synchronous: a cancelled/disconnected response must be
        # able to free its slot without awaiting a lock that cancellation can
        # interrupt. All mutation happens on the single event-loop thread.
        if lease.released:
            return
        lease.released = True
        self._in_flight.discard(lease.user_id)
        self._global = max(0, self._global - 1)


speech_admission = SpeechAdmission(
    rate_per_minute=settings.REVORA_SPEECH_RATE_PER_MINUTE,
    capacity=settings.REVORA_SPEECH_MAX_CONCURRENT_REQUESTS,
)
