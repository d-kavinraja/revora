"""Session-aware hosted Ollama availability monitoring and wake orchestration.

This service is the backend source of truth for *whether the hosted machine and
its Ollama runtime are available*. It is driven by the existing authenticated
browser-tab heartbeat (``user_presence``), never by anonymous requests or by
individual frontend components.

Design constraints:

* No wake without an authenticated, recently-active session and an enabled,
  admin-approved hosted provider.
* Transport errors are shared across users and workers: short Redis leases when
  Redis is available, an optimistic DB-lease fallback otherwise. Only a wake
  *operation* gets a lease — never a persistent machine-awake lease, so the
  machine still idles naturally.
* A wake API response is never treated as readiness. Ollama itself must answer
  ``/api/version`` (bounded backoff polling), and discovery must be accessible
  before the state becomes ``connected``.
* No model loading, unloading or inference. No credentials or endpoint URLs in
  shared state, logs or API responses.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.platform import PlatformSetting
from app.services import hosted_ollama_service as hosted
from app.services import user_presence

logger = logging.getLogger(__name__)

STATE_KEY = "hosted_ollama_state"
COORD_KEY = "hosted_ollama_coordination"
STATE_CACHE_TTL_S = 5.0

DEFAULT_STATE: dict[str, Any] = {
    "state": "unchecked",
    "reason": None,
    "version": None,
    "discovery_ok": False,
    "last_monitor_at": None,
    "last_success_at": None,
    "last_wake_at": None,
    "cooldown_until": None,
    "updated_at": None,
}

_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""

_state_cache: dict[str, Any] | None = None
_state_cache_at: float = 0.0
_pending_task: asyncio.Task | None = None
_coord_lock = asyncio.Lock()


# --- time helpers -----------------------------------------------------------


def _iso(ts: float | None = None) -> str | None:
    if ts is None:
        return datetime.now(UTC).isoformat()
    return datetime.fromtimestamp(ts, tz=UTC).isoformat()


# --- shared availability state ---------------------------------------------


def _normalize_state(raw: dict[str, Any] | None) -> dict[str, Any]:
    state = dict(DEFAULT_STATE)
    if isinstance(raw, dict):
        for key in DEFAULT_STATE:
            if key in raw:
                state[key] = raw[key]
    return state


async def get_state(db: AsyncSession | None = None, *, force: bool = False) -> dict[str, Any]:
    """Read the shared state (fail-open, TTL-cached; no secrets stored)."""
    global _state_cache, _state_cache_at
    if not force and _state_cache is not None:
        if time.monotonic() - _state_cache_at < STATE_CACHE_TTL_S:
            return dict(_state_cache)
    raw: dict[str, Any] | None = None
    try:
        if db is not None:
            result = await db.execute(
                select(PlatformSetting).where(PlatformSetting.key == STATE_KEY)
            )
            row = result.scalars().first()
            raw = row.value if row is not None and isinstance(row.value, dict) else None
        else:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(PlatformSetting).where(PlatformSetting.key == STATE_KEY)
                )
                row = result.scalars().first()
                raw = row.value if row is not None and isinstance(row.value, dict) else None
    except Exception:
        logger.warning("Hosted monitor state read failed; using last known state")
        if db is not None:
            try:
                await db.rollback()
            except Exception:
                pass
        return dict(_state_cache or DEFAULT_STATE)
    state = _normalize_state(raw)
    _state_cache = dict(state)
    _state_cache_at = time.monotonic()
    return state


async def set_state(**updates: Any) -> dict[str, Any]:
    """Write only changed state fields; the caller never commits credentials."""
    global _state_cache, _state_cache_at
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PlatformSetting).where(PlatformSetting.key == STATE_KEY)
        )
        row = result.scalars().first()
        current = _normalize_state(row.value if row is not None and isinstance(row.value, dict) else None)
        new = dict(current)
        for key, value in updates.items():
            if key in DEFAULT_STATE:
                new[key] = value
        new["updated_at"] = _iso()
        changed = any(
            current.get(key) != new.get(key) for key in DEFAULT_STATE
        )
        if not changed:
            _state_cache = dict(new)
            _state_cache_at = time.monotonic()
            return new
        for _attempt in range(3):
            row = (
                await db.execute(
                    select(PlatformSetting).where(PlatformSetting.key == STATE_KEY)
                )
            ).scalars().first()
            version = int(row.version) if row is not None else None
            merged = dict(new)
            if version is not None and row is not None and isinstance(row.value, dict):
                merged = _normalize_state(row.value)
                for key, value in updates.items():
                    if key in DEFAULT_STATE:
                        merged[key] = value
                merged["updated_at"] = _iso()
            if await _coord_upsert(db, merged, version, key=STATE_KEY):
                new = merged
                break
    _state_cache = dict(new)
    _state_cache_at = time.monotonic()
    return new


def reset_runtime_state() -> None:
    """Test-only helper to clear the in-process cache and pending task."""
    global _state_cache, _state_cache_at, _pending_task
    _state_cache = None
    _state_cache_at = 0.0
    _pending_task = None


# --- coordination (Redis leases, DB-backed fallback) -----------------------


async def _coord_upsert(
    db: AsyncSession, value: dict[str, Any], version: int | None, key: str = COORD_KEY
) -> bool:
    """Write a settings row, losing gracefully to a concurrent writer."""
    if version is None:
        try:
            db.add(PlatformSetting(key=key, value=value, version=1))
            await db.commit()
            return True
        except IntegrityError:
            await db.rollback()
            return False
    result = await db.execute(
        update(PlatformSetting)
        .where(PlatformSetting.key == key, PlatformSetting.version == version)
        .values(value=value, version=version + 1)
    )
    if result.rowcount != 1:
        await db.rollback()
        return False
    await db.commit()
    return True


async def _claim_db(kind: str, ttl: float, owner: str) -> bool:
    async with AsyncSessionLocal() as db:
        for _attempt in range(3):
            result = await db.execute(
                select(PlatformSetting).where(PlatformSetting.key == COORD_KEY)
            )
            row = result.scalars().first()
            value = dict(row.value) if row is not None and isinstance(row.value, dict) else {}
            now = time.time()
            until = float(value.get(f"{kind}_until", 0) or 0)
            holder = value.get(f"{kind}_owner")
            if until > now and holder and holder != owner:
                return False
            new = dict(value)
            new[f"{kind}_until"] = now + ttl
            new[f"{kind}_owner"] = owner
            if await _coord_upsert(
                db, new, int(row.version) if row is not None else None
            ):
                return True
        return False


async def _release_db(kind: str, owner: str) -> None:
    async with AsyncSessionLocal() as db:
        for _attempt in range(3):
            result = await db.execute(
                select(PlatformSetting).where(PlatformSetting.key == COORD_KEY)
            )
            row = result.scalars().first()
            if row is None or not isinstance(row.value, dict):
                return
            value = dict(row.value)
            if value.get(f"{kind}_owner") != owner:
                return
            value[f"{kind}_until"] = 0
            value[f"{kind}_owner"] = None
            if await _coord_upsert(db, value, int(row.version)):
                return


async def _claim(kind: str, ttl: float) -> tuple[bool, str, str]:
    """Return ``(acquired, owner, mode)`` for a short-lived coordination lease."""
    owner = uuid.uuid4().hex
    client = await hosted.redis_client()
    if client is not None:
        key = f"revora:hosted:monitor:{kind}"
        try:
            acquired = await client.set(key, owner, nx=True, ex=max(1, int(ttl)))
            if acquired:
                return True, owner, "redis"
            return False, owner, "redis"
        except Exception:
            logger.warning("Hosted monitor Redis claim failed; using DB fallback")
    # Serialize same-process claims; the DB version check covers other workers.
    async with _coord_lock:
        return await _claim_db(kind, ttl, owner), owner, "db"


async def _release(kind: str, owner: str, mode: str) -> None:
    if mode == "redis":
        client = await hosted.redis_client()
        if client is not None:
            try:
                await client.eval(
                    _RELEASE_LUA, 1, f"revora:hosted:monitor:{kind}", owner
                )
                return
            except Exception:
                logger.warning("Hosted monitor Redis release failed; using DB fallback")
    await _release_db(kind, owner)


async def get_cooldown() -> float:
    """Return the shared wake-cooldown deadline as a Unix timestamp."""
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(PlatformSetting).where(PlatformSetting.key == COORD_KEY)
            )
            row = result.scalars().first()
            if row is not None and isinstance(row.value, dict):
                return float(row.value.get("cooldown_until", 0) or 0)
    except Exception:
        logger.warning("Hosted monitor cooldown read failed; assuming none")
    return 0.0


async def set_cooldown(until: float) -> None:
    """Persist a wake cooldown shared by every worker."""
    async with AsyncSessionLocal() as db:
        for _attempt in range(3):
            result = await db.execute(
                select(PlatformSetting).where(PlatformSetting.key == COORD_KEY)
            )
            row = result.scalars().first()
            value = dict(row.value) if row is not None and isinstance(row.value, dict) else {}
            value["cooldown_until"] = float(until)
            if await _coord_upsert(
                db, value, int(row.version) if row is not None else None
            ):
                return


# --- monitor cycle ----------------------------------------------------------


async def _run_check() -> None:
    await set_state(last_monitor_at=_iso())
    probe = await hosted.probe_ollama()
    if probe.ok:
        snapshot = await hosted.get_snapshot(None, force=False)
        if snapshot.reachable:
            await set_state(
                state="connected",
                reason=None,
                version=probe.version or snapshot.version,
                discovery_ok=True,
                last_success_at=_iso(),
                cooldown_until=None,
            )
        else:
            await set_state(
                state="error",
                reason="Model discovery is unavailable.",
                version=probe.version,
                discovery_ok=False,
            )
        return

    # Only a transport failure is compatible with a suspended machine.
    if probe.category in ("config", "auth", "http", "invalid"):
        await set_state(state="error", reason=probe.error, discovery_ok=False)
        return

    cooldown_until = await get_cooldown()
    if cooldown_until > time.time():
        await set_state(
            state="wake_cooldown",
            reason="Hosted wake is cooling down.",
            discovery_ok=False,
            cooldown_until=_iso(cooldown_until),
        )
        return

    if not settings.REVORA_HOSTED_WAKE_ENABLED or not hosted.wake_status()["configured"]:
        await set_state(
            state="unreachable",
            reason=probe.error or "Hosted Ollama is unreachable.",
            discovery_ok=False,
        )
        return

    ttl = settings.REVORA_HOSTED_READY_TIMEOUT_S + 30.0
    acquired, owner, mode = await _claim("wake", ttl)
    if not acquired:
        await set_state(
            state="waking",
            reason="A wake operation is already in progress.",
            discovery_ok=False,
        )
        return
    try:
        await set_state(
            state="waking", reason=probe.error, last_wake_at=_iso(), discovery_ok=False
        )
        result = await hosted.call_wake()
        if result.retry_after:
            until = time.time() + min(
                max(float(result.retry_after), 1.0),
                settings.REVORA_HOSTED_WAKE_COOLDOWN_S * 4,
            )
            await set_cooldown(until)
            await set_state(cooldown_until=_iso(until))
        if result.conflict:
            await set_state(
                state="waking",
                reason="Wake already in progress on the machine.",
                discovery_ok=False,
            )
            return
        if not result.accepted:
            if result.retry_after is None:
                until = time.time() + settings.REVORA_HOSTED_WAKE_COOLDOWN_S
                await set_cooldown(until)
                await set_state(cooldown_until=_iso(until))
            await set_state(
                state="error", reason=result.error or "Wake request failed.", discovery_ok=False
            )
            return

        await set_state(state="connecting", reason=None, discovery_ok=False)
        if not await hosted.wait_for_ready():
            await set_state(
                state="unreachable",
                reason="Hosted Ollama did not become ready after wake.",
                discovery_ok=False,
            )
            return
        await set_state(state="verifying", reason=None, discovery_ok=False)
        snapshot = await hosted.get_snapshot(None, force=True)
        if snapshot.reachable:
            await set_state(
                state="connected",
                reason=None,
                version=snapshot.version,
                discovery_ok=True,
                last_success_at=_iso(),
                cooldown_until=None,
            )
        else:
            await set_state(
                state="error",
                reason="Model discovery failed after wake.",
                discovery_ok=False,
            )
    finally:
        await _release("wake", owner, mode)


async def _monitor_cycle() -> None:
    try:
        async with AsyncSessionLocal() as db:
            enabled = await hosted.is_enabled(db)
            active = await user_presence.has_active_session(db)
    except Exception:
        logger.warning("Hosted monitor gate check failed; skipping cycle")
        return
    # The gate session is closed before any state write opens its own session.
    if not enabled:
        await set_state(state="disabled", reason=None, discovery_ok=False)
        return
    if not active:
        return

    acquired, _owner, _mode = await _claim(
        "tick", settings.REVORA_HOSTED_MONITOR_INTERVAL_S
    )
    if not acquired:
        return
    # The tick lease is intentionally NOT released: it expires on its own so it
    # enforces the global minimum interval across workers and heartbeats.
    await _run_check()


def _task_done(task: asyncio.Task) -> None:
    global _pending_task
    if _pending_task is task:
        _pending_task = None
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning("Hosted monitor cycle failed: %s", type(exc).__name__)


def notify_session_activity() -> bool:
    """Schedule a deduplicated, nonblocking monitor cycle from a heartbeat.

    Safe to call on every heartbeat: at most one cycle is pending per worker,
    and the shared tick lease prevents duplicate work across workers.
    """
    global _pending_task
    if not settings.REVORA_HOSTED_MONITOR_ENABLED:
        return False
    if not settings.REVORA_HOSTED_OLLAMA_ENABLED:
        return False
    if _pending_task is not None and not _pending_task.done():
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    _pending_task = loop.create_task(_monitor_cycle(), name="hosted-monitor")
    _pending_task.add_done_callback(_task_done)
    return True


async def cancel_pending() -> None:
    """Cancel a pending cycle at application shutdown (best effort)."""
    global _pending_task
    task = _pending_task
    _pending_task = None
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
