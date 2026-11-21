"""Administrator-controlled automatic kLLM model loading.

Policy is persisted in the existing ``platform_settings`` table under
``kllm_autoload`` (no migration). Three independent, default-disabled policies
exist:

* ``review_autoload`` — a review may request its exact mapped model when the
  model is unloaded.
* ``login_preload`` — a best-effort, one-shot load request after a successful
  password/GitHub login.
* ``active_session_autoload`` — an active Revora browser tab may request a load
  when kLLM has retired an approved model. This never unloads anything.

Explicit administrative unloads are persisted separately under
``kllm_manual_unloads`` and take precedence over every automatic path until an
administrator explicitly clears the block. kLLM stays authoritative for model,
backend and GPU lifecycle; this module only decides whether Revora may ask kLLM
to load an approved model, then waits for genuine readiness.
"""

from __future__ import annotations

import asyncio
import logging
import time
import zlib
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.platform import PlatformSetting
from app.services import kllm_service
from app.services.kllm_service import (
    KllmConflictError,
    KllmDisabledError,
    KllmError,
    KllmUnavailableError,
    canonical_model,
)

logger = logging.getLogger(__name__)

KLLM_AUTOLOAD_KEY = "kllm_autoload"
KLLM_MANUAL_BLOCK_KEY = "kllm_manual_unloads"

DEFAULT_POLICY: dict[str, Any] = {
    "review_autoload": {"enabled": False, "allowed_models": []},
    "login_preload": {"enabled": False, "allowed_models": []},
    "active_session_autoload": {"enabled": False, "allowed_models": []},
    "load_timeout_seconds": 1200,
    "max_concurrent_loads": 1,
    "login_preload_cooldown_seconds": 300,
    "changed_at": None,
    "changed_by": None,
    "version": 0,
}

_POLICY_GROUPS = ("review_autoload", "login_preload", "active_session_autoload")

_MIN_TIMEOUT = 30
_MAX_TIMEOUT = 3600
_MAX_CONCURRENT = 5
_MAX_COOLDOWN = 86_400
_POLL_INTERVAL_SECONDS = 3.0

# PostgreSQL advisory-lock settings. Session locks are held on a dedicated,
# pinned connection for the lifetime of one lifecycle decision. Contention or
# lookup failure is never treated as successful acquisition.
_ADVISORY_LOCK_ATTEMPTS = 20
_ADVISORY_LOCK_RETRY_SECONDS = 0.25
_GLOBAL_SLOT_LOCK_ATTEMPTS = 40
_GLOBAL_SLOT_RETRY_SECONDS = 0.25

#: Process-local deduplication. On PostgreSQL the global load limit is enforced
#: by advisory slots, so these values are only the SQLite/dev fallback.
_model_locks: dict[str, asyncio.Lock] = {}
_global_gate_lock = asyncio.Lock()
_global_semaphore: tuple[int, asyncio.Semaphore] | None = None
_global_active = 0
_global_waiters = 0
_login_last_request: dict[str, float] = {}


def _canonical_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    models: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        key = canonical_model(item)
        if key and key not in seen:
            seen.add(key)
            models.append(key)
    return sorted(models)


def _clamp_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _normalize_policy(raw: dict[str, Any] | None, version: int = 0) -> dict[str, Any]:
    value: dict[str, Any] = {
        "load_timeout_seconds": DEFAULT_POLICY["load_timeout_seconds"],
        "max_concurrent_loads": DEFAULT_POLICY["max_concurrent_loads"],
        "login_preload_cooldown_seconds": DEFAULT_POLICY[
            "login_preload_cooldown_seconds"
        ],
        "changed_at": None,
        "changed_by": None,
        "version": int(version or 0),
    }
    for group in _POLICY_GROUPS:
        value[group] = {
            "enabled": False,
            "allowed_models": [],
        }
    if isinstance(raw, dict):
        for group in _POLICY_GROUPS:
            stored = raw.get(group)
            if isinstance(stored, dict):
                value[group] = {
                    "enabled": bool(stored.get("enabled", False)),
                    "allowed_models": _canonical_list(
                        stored.get("allowed_models")
                    ),
                }
        value["load_timeout_seconds"] = _clamp_int(
            raw.get("load_timeout_seconds"),
            DEFAULT_POLICY["load_timeout_seconds"],
            _MIN_TIMEOUT,
            _MAX_TIMEOUT,
        )
        value["max_concurrent_loads"] = _clamp_int(
            raw.get("max_concurrent_loads"),
            DEFAULT_POLICY["max_concurrent_loads"],
            1,
            _MAX_CONCURRENT,
        )
        value["login_preload_cooldown_seconds"] = _clamp_int(
            raw.get("login_preload_cooldown_seconds"),
            DEFAULT_POLICY["login_preload_cooldown_seconds"],
            0,
            _MAX_COOLDOWN,
        )
        for key in ("changed_at", "changed_by"):
            item = raw.get(key)
            if item is not None:
                value[key] = str(item)
    return value


async def get_policy(
    db: AsyncSession | None = None, *, force: bool = True
) -> dict[str, Any]:
    """Read the authoritative policy from the database.

    ``force`` exists for call-site clarity: this reader never serves a cached
    policy, so a worker in another process cannot act on a stale switch.
    """
    del force
    try:
        if db is not None:
            result = await db.execute(
                select(PlatformSetting).where(
                    PlatformSetting.key == KLLM_AUTOLOAD_KEY
                )
            )
            row = result.scalars().first()
            raw = row.value if row is not None and isinstance(row.value, dict) else None
            return _normalize_policy(raw, int(row.version or 1) if row else 0)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(PlatformSetting).where(
                    PlatformSetting.key == KLLM_AUTOLOAD_KEY
                )
            )
            row = result.scalars().first()
            raw = row.value if row is not None and isinstance(row.value, dict) else None
            return _normalize_policy(raw, int(row.version or 1) if row else 0)
    except Exception:
        logger.warning(
            "kLLM autoload policy read failed; automatic loading stays disabled",
            exc_info=True,
        )
        return _normalize_policy(None, 0)


async def update_policy(
    db: AsyncSession,
    updates: dict[str, Any],
    *,
    admin_id: Any = None,
    expected_version: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any], int | None]:
    """Persist a validated policy update.

    Returns ``(new, prior, conflict_version)``. A non-None conflict version
    means nothing was written and the caller should answer 409.
    """
    await db.flush()
    result = await db.execute(
        select(PlatformSetting)
        .where(PlatformSetting.key == KLLM_AUTOLOAD_KEY)
        .with_for_update()
    )
    row = result.scalars().first()
    row_version = int(row.version or 1) if row is not None else 0
    prior_raw = row.value if row is not None and isinstance(row.value, dict) else None
    prior = _normalize_policy(prior_raw, row_version)

    if expected_version is not None and int(expected_version) != row_version:
        return dict(prior), dict(prior), row_version

    merged = dict(prior)
    for group in _POLICY_GROUPS:
        incoming = updates.get(group)
        if isinstance(incoming, dict):
            merged[group] = {**prior[group], **incoming}
    for key in (
        "load_timeout_seconds",
        "max_concurrent_loads",
        "login_preload_cooldown_seconds",
    ):
        if key in updates:
            merged[key] = updates[key]

    new_value = _normalize_policy(merged, row_version + 1)
    new_value["changed_at"] = datetime.now(UTC).isoformat()
    new_value["changed_by"] = str(admin_id) if admin_id is not None else "system"

    if row is None:
        row = PlatformSetting(
            key=KLLM_AUTOLOAD_KEY,
            value=new_value,
            updated_by=admin_id,
            version=1,
        )
        db.add(row)
    else:
        row.value = new_value
        row.updated_by = admin_id
        row.version = row_version + 1
        db.add(row)
    return dict(new_value), prior, None


# --- durable manual-unload precedence ---------------------------------------


def _normalize_manual_blocks(raw: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    blocks: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, dict):
        return blocks
    for key, value in raw.items():
        canonical = canonical_model(key)
        if not canonical or not isinstance(value, dict):
            continue
        blocks[canonical] = {
            "model": canonical,
            "blocked_at": str(value.get("blocked_at") or ""),
            "blocked_by": str(value.get("blocked_by") or ""),
            "reason": str(value.get("reason") or "admin_unload"),
        }
    return blocks


async def _read_manual_blocks(
    db: AsyncSession, *, for_update: bool = False
) -> tuple[dict[str, dict[str, Any]], PlatformSetting | None, int]:
    query = select(PlatformSetting).where(PlatformSetting.key == KLLM_MANUAL_BLOCK_KEY)
    if for_update:
        query = query.with_for_update()
    result = await db.execute(query)
    row = result.scalars().first()
    version = int(row.version or 1) if row is not None else 0
    raw = row.value if row is not None and isinstance(row.value, dict) else None
    return _normalize_manual_blocks(raw), row, version


async def get_manual_blocks(
    db: AsyncSession | None = None, *, force: bool = True
) -> dict[str, dict[str, Any]]:
    del force
    try:
        if db is not None:
            blocks, _, _ = await _read_manual_blocks(db)
            return blocks
        async with AsyncSessionLocal() as session:
            blocks, _, _ = await _read_manual_blocks(session)
            return blocks
    except Exception:
        logger.warning(
            "kLLM manual-unload block read failed; automatic loading stays blocked",
            exc_info=True,
        )
        # Fail closed: an unreadable block store must never silently allow a
        # load that an administrator explicitly stopped.
        return {"__unverifiable__": {"model": "__unverifiable__"}}


async def is_manually_blocked(db: AsyncSession, model: str) -> bool:
    canonical = canonical_model(model)
    if not canonical:
        return True
    blocks = await get_manual_blocks(db, force=True)
    return canonical in blocks or "__unverifiable__" in blocks


async def set_manual_block(
    db: AsyncSession, model: str, *, admin_id: Any, reason: str = "admin_unload"
) -> dict[str, dict[str, Any]]:
    canonical = canonical_model(model)
    if not canonical:
        raise ValueError("A model is required for a manual-unload block.")
    blocks, row, version = await _read_manual_blocks(db, for_update=True)
    blocks[canonical] = {
        "model": canonical,
        "blocked_at": datetime.now(UTC).isoformat(),
        "blocked_by": str(admin_id),
        "reason": reason,
    }
    value = dict(blocks)
    if row is None:
        db.add(
            PlatformSetting(
                key=KLLM_MANUAL_BLOCK_KEY,
                value=value,
                updated_by=admin_id,
                version=1,
            )
        )
    else:
        row.value = value
        row.updated_by = admin_id
        row.version = version + 1
        db.add(row)
    return blocks


async def clear_manual_block(db: AsyncSession, model: str) -> bool:
    canonical = canonical_model(model)
    if not canonical:
        return False
    blocks, row, version = await _read_manual_blocks(db, for_update=True)
    if canonical not in blocks:
        return False
    blocks.pop(canonical, None)
    if row is not None:
        row.value = dict(blocks)
        row.version = version + 1
        db.add(row)
    return True


def manual_block_payload(blocks: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [blocks[key] for key in sorted(blocks)]


# --- policy helpers ----------------------------------------------------------


def review_allows(policy: dict[str, Any], model: str) -> bool:
    group = policy.get("review_autoload") or {}
    if not group.get("enabled"):
        return False
    return canonical_model(model) in set(group.get("allowed_models") or [])


def login_models(policy: dict[str, Any]) -> list[str]:
    group = policy.get("login_preload") or {}
    if not group.get("enabled"):
        return []
    return list(group.get("allowed_models") or [])


def session_models(policy: dict[str, Any]) -> list[str]:
    group = policy.get("active_session_autoload") or {}
    if not group.get("enabled"):
        return []
    return list(group.get("allowed_models") or [])


# --- locking and load request plumbing --------------------------------------


def _lock_for(model: str) -> asyncio.Lock:
    lock = _model_locks.get(model)
    if lock is None:
        lock = asyncio.Lock()
        _model_locks[model] = lock
    return lock


def _is_postgres(db: AsyncSession) -> bool:
    dialect = getattr(db.get_bind(), "dialect", None)
    return dialect is not None and getattr(dialect, "name", None) == "postgresql"


@asynccontextmanager
async def _pinned_postgres_connection(db: AsyncSession):
    """Pin one physical connection for the lifetime of an advisory lock.

    The AsyncSession's own connection cannot be used here: a commit inside a
    lock scope returns that connection to the pool. Advisory locks are tied to
    the physical connection, so they must be acquired and released here.

    Use the AsyncEngine from the session (db.bind) rather than the sync
    Engine from get_bind() to avoid MissingGreenlet with asyncpg.
    """
    if not _is_postgres(db):
        raise KllmUnavailableError(
            "PostgreSQL coordination is required for this operation.",
            reason_code="lifecycle_coordination_unavailable",
        )
    engine = getattr(db, "bind", None)
    if not isinstance(engine, AsyncEngine):
        raise KllmUnavailableError(
            "A dedicated PostgreSQL connection could not be obtained.",
            reason_code="lifecycle_coordination_unavailable",
        )
    async with engine.connect() as connection:
        yield connection


async def _try_pg_advisory(connection, key: int, *, reason_code: str) -> bool:
    try:
        return bool(await connection.scalar(select(func.pg_try_advisory_lock(key))))
    except Exception as exc:
        raise KllmUnavailableError(
            "kLLM coordination state could not be verified.",
            reason_code=reason_code,
        ) from exc


async def _unlock_pg_advisory(connection, key: int) -> None:
    """Unlock on the same connection, invalidating it if unlock is ambiguous."""
    try:
        unlocked = bool(
            await connection.scalar(select(func.pg_advisory_unlock(key)))
        )
        if not unlocked:
            raise RuntimeError("pg_advisory_unlock did not release the lock")
        commit = getattr(connection, "commit", None)
        if callable(commit):
            await commit()
        return
    except Exception:
        logger.warning("kLLM advisory unlock failed; invalidating connection")
    invalidate = getattr(connection, "invalidate", None)
    if callable(invalidate):
        try:
            await invalidate()
        except Exception:
            logger.debug("kLLM advisory-lock connection invalidation failed")


async def _unlock_pg_advisory_keys(connection, keys: list[int]) -> None:
    for key in reversed(keys):
        await _unlock_pg_advisory(connection, key)


@asynccontextmanager
async def model_operation_lock(db: AsyncSession, model: str):
    """Serialize one model's Revora lifecycle decisions across processes."""
    async with _lock_for(model), _cross_process_lock(db, model):
        yield


@asynccontextmanager
async def _cross_process_lock(db: AsyncSession, model: str):
    """Hold a PostgreSQL session advisory lock around one lifecycle decision.

    The lock is acquired on a dedicated pinned connection and released on that
    same connection. Contention, lookup errors and retry exhaustion fail closed.
    SQLite and other dialects only use the process-local model lock.
    """
    if not _is_postgres(db):
        yield
        return

    key = zlib.crc32(f"revora:kllm:lifecycle:{model}".encode()) & 0x7FFFFFFF
    async with _pinned_postgres_connection(db) as connection:
        acquired = False
        try:
            for attempt in range(_ADVISORY_LOCK_ATTEMPTS):
                acquired = await _try_pg_advisory(
                    connection, key, reason_code="lifecycle_lock_unavailable"
                )
                if acquired:
                    break
                if attempt + 1 < _ADVISORY_LOCK_ATTEMPTS:
                    await asyncio.sleep(_ADVISORY_LOCK_RETRY_SECONDS)
            if not acquired:
                raise KllmUnavailableError(
                    "Another process is changing this kLLM model right now. "
                    "Retry the operation.",
                    reason_code="lifecycle_lock_busy",
                )
            try:
                yield
            finally:
                if acquired:
                    await _unlock_pg_advisory(connection, key)
        finally:
            # Closing the pinned connection returns it to the pool. If unlock
            # failed, _unlock_pg_advisory invalidated it so PostgreSQL drops the
            # session (and every session-level lock it owns) immediately.
            acquired = False


async def _acquire_global_local(limit: int) -> asyncio.Semaphore:
    """SQLite/dev fallback for the global automatic-load limit."""
    global _global_semaphore, _global_active, _global_waiters
    async with _global_gate_lock:
        if (
            _global_semaphore is None
            or (
                _global_semaphore[0] != limit
                and _global_active == 0
                and _global_waiters == 0
            )
        ):
            _global_semaphore = (limit, asyncio.Semaphore(limit))
        semaphore = _global_semaphore[1]
        _global_waiters += 1

    acquired = False
    accounted = False
    try:
        await semaphore.acquire()
        acquired = True
        # Waiter decrement and active increment happen in one gate section, so
        # a limit change can never observe "idle" while a permit is held.
        async with _global_gate_lock:
            _global_waiters -= 1
            _global_active += 1
            accounted = True
        return semaphore
    finally:
        if not accounted:
            async with _global_gate_lock:
                _global_waiters -= 1
            if acquired:
                semaphore.release()


async def _release_global_local(semaphore: asyncio.Semaphore) -> None:
    global _global_active
    async with _global_gate_lock:
        _global_active = max(0, _global_active - 1)
    semaphore.release()


def _global_slot_key(slot: int) -> int:
    return zlib.crc32(f"revora:kllm:global-slot:{slot}".encode()) & 0x7FFFFFFF


async def _acquire_global_slot(connection, limit: int) -> tuple[int, int]:
    """Claim one of the first ``limit`` global advisory slots."""
    bounded = max(1, min(int(limit), _MAX_CONCURRENT))
    slots = list(range(bounded))
    for attempt in range(_GLOBAL_SLOT_LOCK_ATTEMPTS):
        for slot in slots:
            key = _global_slot_key(slot)
            if await _try_pg_advisory(
                connection, key, reason_code="global_load_gate_unavailable"
            ):
                return slot, key
        if attempt + 1 < _GLOBAL_SLOT_LOCK_ATTEMPTS:
            await asyncio.sleep(_GLOBAL_SLOT_RETRY_SECONDS)
    raise KllmUnavailableError(
        "The global kLLM automatic-load limit is busy. Retry shortly.",
        reason_code="global_load_limit_busy",
    )


@asynccontextmanager
async def _global_capacity(db: AsyncSession, policy: dict[str, Any]):
    """Hold one system-wide automatic-load permit.

    PostgreSQL uses advisory slots so API and worker processes share one limit.
    SQLite keeps the process-local fallback used by tests and local dev.
    """
    if not _is_postgres(db):
        semaphore = await _acquire_global_local(int(policy["max_concurrent_loads"]))
        try:
            yield
        finally:
            await _release_global_local(semaphore)
        return

    active_policy = policy
    expected_version = int(active_policy.get("version") or 0)
    for _ in range(2):
        async with _pinned_postgres_connection(db) as connection:
            _slot, key = await _acquire_global_slot(
                connection, int(active_policy["max_concurrent_loads"])
            )
            released = False
            try:
                fresh_policy = await get_policy(db, force=True)
                fresh_version = int(fresh_policy.get("version") or 0)
                if fresh_version != expected_version:
                    await _unlock_pg_advisory(connection, key)
                    released = True
                    active_policy = fresh_policy
                    expected_version = fresh_version
                    continue
                try:
                    yield
                finally:
                    await _unlock_pg_advisory(connection, key)
                    released = True
                return
            finally:
                if not released:
                    await _unlock_pg_advisory(connection, key)
    raise KllmUnavailableError(
        "The automatic-loading policy changed repeatedly. Retry the request.",
        reason_code="policy_version_conflict",
    )


@asynccontextmanager
async def hold_global_load_gate(db: AsyncSession):
    """Quiesce all global load slots so the limit can be changed safely."""
    if not _is_postgres(db):
        yield
        return

    async with _pinned_postgres_connection(db) as connection:
        all_keys = [_global_slot_key(slot) for slot in range(_MAX_CONCURRENT)]
        acquired: list[int] = []
        try:
            for attempt in range(_GLOBAL_SLOT_LOCK_ATTEMPTS):
                acquired = []
                try:
                    for key in all_keys:
                        if not await _try_pg_advisory(
                            connection,
                            key,
                            reason_code="global_load_gate_unavailable",
                        ):
                            break
                        acquired.append(key)
                except Exception:
                    await _unlock_pg_advisory_keys(connection, acquired)
                    acquired = []
                    raise
                if len(acquired) == len(all_keys):
                    break
                await _unlock_pg_advisory_keys(connection, acquired)
                acquired = []
                if attempt + 1 < _GLOBAL_SLOT_LOCK_ATTEMPTS:
                    await asyncio.sleep(_GLOBAL_SLOT_RETRY_SECONDS)
            if len(acquired) != len(all_keys):
                raise KllmConflictError(
                    "Automatic model loads are active. Retry this policy change.",
                    reason_code="global_loads_active",
                )
            yield
        finally:
            await _unlock_pg_advisory_keys(connection, acquired)


async def _read_model(db: AsyncSession, model: str):
    snapshot = await kllm_service.get_snapshot(db, force=True)
    if not snapshot.reachable:
        raise KllmUnavailableError(
            snapshot.error or "kLLM is unreachable. The model cannot be verified."
        )
    if snapshot.stale:
        raise KllmUnavailableError(
            "kLLM state is stale; the model cannot be verified right now."
        )
    match = next((m for m in snapshot.models if m.key == model), None)
    if match is None:
        raise KllmUnavailableError(f"Model '{model}' is not available in kLLM.")
    return match


async def _assert_load_allowed(db: AsyncSession, model: str) -> None:
    """Enforce admin controls that are independent of the three policies."""
    from app.services.model_overrides import model_overrides_service

    canonical = canonical_model(model)
    if await model_overrides_service.is_model_disabled(db, kllm_service.KLLM_SLUG, canonical):
        raise KllmConflictError(
            f"Model '{canonical}' is disabled by an administrator.",
            definitive=True,
            reason_code="admin_disabled",
        )
    if await is_manually_blocked(db, canonical):
        raise KllmConflictError(
            f"Automatic loading of '{canonical}' is blocked because an "
            "administrator unloaded it.",
            definitive=True,
            reason_code="manual_unload",
        )


async def _request_load_once(
    db: AsyncSession, model: str, policy: dict[str, Any]
) -> dict[str, Any]:
    """Issue one load request; caller must hold ``model_operation_lock``."""
    async with _global_capacity(db, policy):
        await _assert_load_allowed(db, model)
        return await kllm_service.request_model_load(db, model)


async def wait_until_ready(
    db: AsyncSession,
    model: str,
    *,
    timeout: int,
    cancel_check: Callable[[], Awaitable[bool]] | None = None,
    allow_recovery: bool = False,
    policy: dict[str, Any] | None = None,
) -> Any:
    """Poll forced kLLM state until the exact model is genuinely ready."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(1, int(timeout))
    last_error = "kLLM has not reported the model as ready yet."
    recovered = False

    while True:
        if cancel_check is not None and await cancel_check():
            raise asyncio.CancelledError()

        try:
            match = await _read_model(db, model)
        except KllmUnavailableError as exc:
            last_error = exc.message
        except KllmConflictError:
            raise
        else:
            if match.ready:
                return match
            if match.status == "failed":
                raise KllmConflictError(
                    f"Model '{model}' failed to load in kLLM.",
                    definitive=True,
                    reason_code="model_failed",
                )
            if match.status == "unloaded":
                active_policy = policy or await get_policy(db, force=True)
                if (
                    allow_recovery
                    and not recovered
                    and review_allows(active_policy, model)
                ):
                    try:
                        async with model_operation_lock(db, model):
                            current = await _read_model(db, model)
                            if current.ready:
                                return current
                            if current.status == "unloaded":
                                await _assert_load_allowed(db, model)
                                await _request_load_once(db, model, active_policy)
                            elif current.status == "failed":
                                raise KllmConflictError(
                                    f"Model '{model}' failed to load in kLLM.",
                                    definitive=True,
                                    reason_code="model_failed",
                                )
                        recovered = True
                        last_error = "kLLM retired the model; load requested again."
                        await asyncio.sleep(min(_POLL_INTERVAL_SECONDS, max(0.05, deadline - loop.time())))
                        continue
                    except KllmError as exc:
                        if exc.definitive:
                            raise
                        last_error = exc.message
                raise KllmUnavailableError(
                    f"Model '{model}' was unloaded while Revora was waiting for it.",
                    reason_code="idle_unloaded",
                )
            last_error = (
                f"Model '{model}' is still loading in kLLM."
                if match.status == "loading"
                else f"Model '{model}' is not ready in kLLM."
            )

        remaining = deadline - loop.time()
        if remaining <= 0:
            raise KllmUnavailableError(
                f"Timed out after {timeout}s waiting for model '{model}'. "
                f"{last_error}",
                reason_code="load_timeout",
            )
        await asyncio.sleep(min(_POLL_INTERVAL_SECONDS, remaining))


async def ensure_model_ready_with_autoload(
    db: AsyncSession,
    model: str,
    *,
    timeout: int | None = None,
    cancel_check: Callable[[], Awaitable[bool]] | None = None,
) -> Any:
    """Primary-first readiness for a review's exact mapped model."""
    canonical = canonical_model(model)
    if not canonical:
        raise KllmUnavailableError("A kLLM model must be selected.")

    if not await kllm_service.is_enabled(db):
        raise KllmDisabledError("The kLLM managed provider is currently disabled.")

    policy = await get_policy(db, force=True)
    wait_seconds = int(timeout or policy["load_timeout_seconds"])

    match = await _read_model(db, canonical)
    if match.ready:
        return match
    if match.status == "failed":
        raise KllmConflictError(
            f"Model '{canonical}' failed to load in kLLM.",
            definitive=True,
            reason_code="model_failed",
        )
    if match.status == "loading":
        return await wait_until_ready(
            db,
            canonical,
            timeout=wait_seconds,
            cancel_check=cancel_check,
            allow_recovery=True,
            policy=policy,
        )
    if match.status != "unloaded":
        raise KllmUnavailableError(
            f"Model '{canonical}' is not ready in kLLM (readiness="
            f"{match.readiness})."
        )

    if not review_allows(policy, canonical):
        raise KllmUnavailableError(
            f"Model '{canonical}' is not loaded and automatic loading is not "
            "enabled for this model by an administrator.",
            definitive=True,
            reason_code="review_autoload_disabled",
        )

    async with model_operation_lock(db, canonical):
        if cancel_check is not None and await cancel_check():
            raise asyncio.CancelledError()
        current = await _read_model(db, canonical)
        if current.ready:
            return current
        if current.status == "failed":
            raise KllmConflictError(
                f"Model '{canonical}' failed to load in kLLM.",
                definitive=True,
                reason_code="model_failed",
            )
        if current.status == "unloaded":
            await _assert_load_allowed(db, canonical)
            await _request_load_once(db, canonical, policy)
        elif current.status != "loading":
            raise KllmUnavailableError(
                f"Model '{canonical}' is not loadable in kLLM right now."
            )

    return await wait_until_ready(
        db,
        canonical,
        timeout=wait_seconds,
        cancel_check=cancel_check,
        allow_recovery=True,
        policy=policy,
    )


async def preload_after_login(user_id: Any) -> None:
    """Best-effort one-shot login preload. Never blocks or fails authentication."""
    del user_id
    try:
        async with AsyncSessionLocal() as db:
            policy = await get_policy(db, force=True)
            models = login_models(policy)
            if not models:
                return
            cooldown = int(policy["login_preload_cooldown_seconds"])
            now = time.monotonic()
            for model in models:
                last = _login_last_request.get(model)
                if cooldown and last is not None and now - last < cooldown:
                    continue
                lock = _lock_for(model)
                if lock.locked():
                    continue
                try:
                    async with model_operation_lock(db, model):
                        current = await _read_model(db, model)
                        if current.ready or current.status == "loading":
                            continue
                        if current.status != "unloaded":
                            continue
                        await _assert_load_allowed(db, model)
                        await _request_load_once(db, model, policy)
                        _login_last_request[model] = time.monotonic()
                except KllmError:
                    continue
                except Exception as exc:
                    logger.warning(
                        "kLLM login preload skipped (%s)", type(exc).__name__
                    )
    except Exception as exc:
        logger.warning("kLLM login preload unavailable (%s)", type(exc).__name__)


def schedule_login_preload(background_tasks: Any, user_id: Any) -> None:
    """Register the preload before any heavier login reconciliation task."""
    if background_tasks is None:
        return
    background_tasks.add_task(preload_after_login, user_id)


async def reconcile_session_models(db: AsyncSession) -> list[dict[str, Any]]:
    """Nonblocking load reconciliation on an active-session heartbeat.

    This never unloads a model. It only asks kLLM to load an approved model that
    kLLM has retired while a browser tab is still active.
    """
    results: list[dict[str, Any]] = []
    try:
        if not await kllm_service.is_enabled(db):
            return results
        from app.services import user_presence

        if not await user_presence.has_active_session(db):
            return results
        policy = await get_policy(db, force=True)
        models = session_models(policy)
        if not models or not await user_presence.has_active_session(db):
            return results
    except Exception as exc:
        logger.debug("kLLM session reconcile skipped (%s)", type(exc).__name__)
        return results

    for model in models:
        projection = {"model": model, "state": "unchanged", "reason_code": "unknown"}
        try:
            async with model_operation_lock(db, model):
                if not await user_presence.has_active_session(db):
                    projection["reason_code"] = "no_active_session"
                    results.append(projection)
                    continue
                current = await _read_model(db, model)
                if current.ready:
                    projection = {
                        "model": model,
                        "state": "ready",
                        "reason_code": "ready",
                    }
                elif current.status == "loading":
                    projection = {
                        "model": model,
                        "state": "loading_model",
                        "reason_code": "model_loading",
                    }
                elif current.status == "failed":
                    projection = {
                        "model": model,
                        "state": "failed",
                        "reason_code": "model_failed",
                    }
                elif current.status == "unloaded":
                    await _assert_load_allowed(db, model)
                    result = await _request_load_once(db, model, policy)
                    projection = {
                        "model": model,
                        "state": "loading_model",
                        "reason_code": "load_requested",
                        "status": result.get("status"),
                    }
                else:
                    projection = {
                        "model": model,
                        "state": "unavailable",
                        "reason_code": "model_unavailable",
                    }
        except KllmError as exc:
            projection = {
                "model": model,
                "state": "unavailable",
                "reason_code": exc.reason_code or "kllm_unavailable",
            }
        except Exception as exc:
            logger.debug("kLLM session model reconcile failed (%s)", type(exc).__name__)
            projection = {
                "model": model,
                "state": "unavailable",
                "reason_code": "reconcile_unavailable",
            }
        results.append(projection)
    return results


# --- explicit admin lifecycle helpers ---------------------------------------


async def manual_unload_model(
    db: AsyncSession,
    model: str,
    *,
    confirm: bool,
    force: bool,
    admin_id: Any,
    disable_always_on: bool = False,
) -> dict[str, Any]:
    """Stop a model and persist durable suppression of automatic reloads."""
    canonical = canonical_model(model)
    if not canonical:
        raise KllmUnavailableError("A kLLM model must be selected.")
    if not confirm:
        raise KllmConflictError(
            "This action requires explicit confirmation."
        )
    async with model_operation_lock(db, canonical):
        always_on_disabled = False
        default_model = await kllm_service.get_default_model(db)
        if canonical == default_model:
            try:
                config = await kllm_service.get_autoscale_config()
            except KllmError as exc:
                raise KllmConflictError(
                    "Cannot verify kLLM's always-on configuration; refusing to "
                    "unload the default model.",
                    definitive=True,
                    reason_code="always_on_unverifiable",
                ) from exc
            if not bool(config.get("verified")):
                raise KllmConflictError(
                    "Cannot verify kLLM's effective always-on configuration; "
                    "refusing to unload the default model.",
                    definitive=True,
                    reason_code="always_on_unverifiable",
                )
            if int(config.get("size") or 0) > 0:
                if not disable_always_on:
                    raise KllmConflictError(
                        "kLLM always-on is enabled for the default model. "
                        "Disable it before unloading this model.",
                        definitive=True,
                        reason_code="always_on_conflict",
                    )
                keep_result = await kllm_service.set_keep(db, 0, confirm=True)
                if not bool(keep_result.get("verified")) or not bool(
                    keep_result.get("effectively_disabled")
                ):
                    raise KllmConflictError(
                        "Revora set kLLM's desired pool to zero, but kLLM still "
                        "enforces an always-on minimum. Change autoscale.min_backends "
                        "in kLLM itself and retry; no model was unloaded.",
                        definitive=True,
                        reason_code="always_on_effective_not_disabled",
                    )
                always_on_disabled = True

        await set_manual_block(db, canonical, admin_id=admin_id)
        # Commit the intent before releasing the cross-process lock. Another
        # process cannot acquire that lock until this block is visible.
        await db.commit()

        result = await kllm_service.unload_model(
            db, canonical, confirm=confirm, force=force
        )
        result["automatic_loading_blocked"] = True
        result["always_on_disabled"] = always_on_disabled
        return result


async def manual_load_model(
    db: AsyncSession, model: str, *, confirm: bool, admin_id: Any
) -> dict[str, Any]:
    """Explicit admin load. A successful request clears a manual-unload block."""
    canonical = canonical_model(model)
    if not canonical:
        raise KllmUnavailableError("A kLLM model must be selected.")
    async with model_operation_lock(db, canonical):
        result = await kllm_service.load_model(db, canonical, confirm=confirm)
        cleared = await clear_manual_block(db, canonical)
        await db.commit()
        result["automatic_loading_blocked"] = False
        result["manual_block_cleared"] = bool(cleared)
        return result


async def clear_manual_block_for_admin(
    db: AsyncSession, model: str, *, admin_id: Any
) -> bool:
    canonical = canonical_model(model)
    if not canonical:
        return False
    async with model_operation_lock(db, canonical):
        cleared = await clear_manual_block(db, canonical)
        if cleared:
            await db.commit()
        return cleared


def admin_policy_payload(policy: dict[str, Any]) -> dict[str, Any]:
    """Full policy shape for the isolated admin API (safe scalars only)."""
    value = _normalize_policy(policy, int(policy.get("version") or 0))
    value["changed_at"] = policy.get("changed_at")
    value["changed_by"] = policy.get("changed_by")
    return value
