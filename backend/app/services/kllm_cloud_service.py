"""kLLM Cloud: catalogue discovery, approval gate and concurrency control.

kLLM Cloud is an independent server-owned provider. It shares the managed-
provider mechanics (no user API key, admin-owned enablement) with the local
kLLM provider but has its own namespace (``kllm-cloud:<model>``), its own
relay configuration and its own per-model approval catalogue.

Discovery is free and never consumes inference quota: ``GET /v1/models`` is
answered by the gateway from its static registry, so it works with no model
backend warm. ``GET /health`` is proxied to a backend and therefore only tells
us whether *some* backend is warm - it is never used as provider liveness and
never as per-model health.

Approval is deny-by-default: a discovered canonical chat model is not
selectable until an administrator approves it, which is expressed as a
``model_overrides`` row for ``(kllm-cloud, <canonical id>)`` whose status is
``available``. Per-surface flags (``chat_enabled`` / ``review_enabled``) live
on the same row, and the global ``status=disabled`` kill switch keeps working
unchanged. Media ids, compatibility aliases and unknown ids are discovered for
admin diagnostics but are never selectable.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.discovered_model import DiscoveredModel
from app.models.platform import ModelOverride
from app.services import kllm_cloud_catalog as catalog
from app.services.kllm_cloud_errors import (
    KllmCloudAuthError,
    KllmCloudBusyError,
    KllmCloudDisabledError,
    KllmCloudError,
    KllmCloudInvalidModelError,
    KllmCloudNotApprovedError,
    KllmCloudNotConfiguredError,
    KllmCloudProtocolError,
    KllmCloudRequestError,
    KllmCloudSurfaceDisabledError,
    KllmCloudTimeoutError,
    KllmCloudUnavailableError,
)
from app.services.model_overrides import model_overrides_service
from app.services.provider_registry import provider_registry_service

logger = logging.getLogger(__name__)

PROVIDER_SLUG = catalog.CLOUD_PROVIDER_SLUG
PROVIDER_NAME = catalog.CLOUD_PROVIDER_NAME
MODEL_PREFIX = catalog.CLOUD_MODEL_PREFIX
CATEGORY = catalog.CLOUD_CATEGORY
DISABLED_MESSAGE = catalog.DISABLED_MESSAGE

#: Minimum spacing between two administrator-triggered catalogue refreshes.
REFRESH_MIN_INTERVAL_S = 10.0

#: /health is a backend-warm probe, not a liveness signal; cache it briefly.
WARM_CACHE_TTL_S = 15.0

__all__ = [
    "CATEGORY",
    "DISABLED_MESSAGE",
    "MODEL_PREFIX",
    "PROVIDER_NAME",
    "PROVIDER_SLUG",
    "CloudModel",
    "CloudSnapshot",
    "KllmCloudError",
    "approve_model",
    "cloud_key",
    "diagnostics",
    "ensure_model_ready",
    "get_chat_models",
    "get_review_models",
    "get_snapshot",
    "invalidate_cache",
    "is_cloud_key",
    "is_configured",
    "is_enabled",
    "model_id_from_key",
    "probe_backend_warm",
    "probe_model_readiness",
    "refresh_catalog",
    "revoke_model",
    "set_surfaces",
]


def cloud_key(model_id: str) -> str:
    return catalog.cloud_key(model_id)


def is_cloud_key(key: str | None) -> bool:
    return catalog.is_cloud_key(key)


def model_id_from_key(key: str | None) -> str | None:
    return catalog.parse_cloud_key(key)


def is_configured() -> bool:
    from app.ai import kllm_cloud_client

    return kllm_cloud_client.kllm_cloud_client.is_configured()


@dataclass(frozen=True)
class CloudModel:
    """One reconciled catalogue entry (advertised or remembered)."""

    model_id: str
    display_name: str
    kind: str
    family: str | None = None
    context_window: int | None = None
    vision: bool = False
    tags: tuple[str, ...] = ()
    description: str | None = None
    canonical: str | None = None
    approved: bool = False
    disabled: bool = False
    chat_enabled: bool = True
    review_enabled: bool = True
    available: bool = True
    ready: bool = False
    reason_code: str = "unknown"
    runtime_state: str = "unknown"
    runtime_reason: str | None = None

    @property
    def key(self) -> str:
        return cloud_key(self.model_id)

    def as_dict(self) -> dict[str, Any]:
        """User-facing catalogue row (ChatModelRead-compatible)."""
        return {
            "key": self.key,
            "provider": PROVIDER_SLUG,
            "category": CATEGORY,
            "display_name": self.display_name,
            "status": "disabled" if self.disabled else "available",
            "loaded": False,
            "ready": self.ready,
            "installed": True,
            "admin_loadable": False,
            "digest": None,
            "last_verified_at": None,
            "runtime_unknown": False,
            "partial": False,
            "load_state": None,
            "readiness": (
                "ready"
                if (self.ready and self.runtime_state == "recently_responded")
                else "unavailable"
                if self.runtime_state == "temporarily_unavailable"
                else "unverified"
                if self.ready
                else "unavailable"
            ),
            "reason_code": self.reason_code,
            "runtime_state": self.runtime_state,
            "runtime_reason": self.runtime_reason,
            "context_window": self.context_window,
            "vision": self.vision,
            "tags": list(self.tags),
            "resident": False,
            "backend_count": 0,
        }

    def as_admin_dict(self) -> dict[str, Any]:
        """Admin projection: adds the classification and alias target."""
        return {
            "model_id": self.model_id,
            "key": self.key,
            "display_name": self.display_name,
            "classification": self.kind,
            "canonical": self.canonical,
            "family": self.family,
            "context_window": self.context_window,
            "vision": self.vision,
            "tags": list(self.tags),
            "description": self.description,
            "approved": self.approved,
            "disabled": self.disabled,
            "chat_enabled": self.chat_enabled,
            "review_enabled": self.review_enabled,
            "available": self.available,
            "ready": self.ready,
            "reason_code": self.reason_code,
            "runtime_state": self.runtime_state,
            "runtime_reason": self.runtime_reason,
        }


@dataclass
class CloudSnapshot:
    enabled: bool = False
    configured: bool = False
    reachable: bool = False
    stale: bool = False
    error: str | None = None
    error_reason: str | None = None
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    fetched_at: float = 0.0
    last_success_at: datetime | None = None
    catalog_ids: tuple[str, ...] = ()
    models: list[CloudModel] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    cache_ttl_s: float = 0.0

    @property
    def state(self) -> str:
        if not self.enabled:
            return "disabled"
        if not self.configured:
            return "unconfigured"
        if not self.reachable:
            return "unreachable"
        if self.stale:
            return "stale"
        return "ready"

    @property
    def reason(self) -> str:
        if not self.enabled:
            return "kllm_cloud_disabled"
        if not self.configured:
            return "kllm_cloud_not_configured"
        if not self.reachable:
            return self.error_reason or "kllm_cloud_unreachable"
        if self.stale:
            return "kllm_cloud_catalog_stale"
        return "ready"


@dataclass(frozen=True)
class _RawCatalog:
    ok: bool
    ids: tuple[str, ...]
    fetched_at: float
    fetched_at_dt: datetime
    error_reason: str | None = None
    error_message: str | None = None
    relay_display: dict[str, str] = field(default_factory=dict)


_cache: _RawCatalog | None = None
_last_success_at: datetime | None = None
_last_success_ids: tuple[str, ...] = ()
_last_success_display: dict[str, str] = {}
_synced_ids: tuple[str, ...] = ()
_lock: asyncio.Lock | None = None
_sync_lock: asyncio.Lock | None = None
_warm_state: dict[str, Any] | None = None
_warm_at: float = 0.0
_last_refresh: float = 0.0
_refresh_task: asyncio.Task | None = None

#: Bounded background readiness probe: one probe per model per cooldown window.
_PROBE_COOLDOWN_S = 300.0
_last_probe_attempt: dict[str, float] = {}
_probe_semaphore: asyncio.Semaphore | None = None


def _get_probe_semaphore() -> asyncio.Semaphore:
    """A single in-flight probe at a time - never a probe storm."""
    global _probe_semaphore
    if _probe_semaphore is None:
        _probe_semaphore = asyncio.Semaphore(1)
    return _probe_semaphore


def invalidate_cache() -> None:
    """Forget the process-local catalogue and warm-probe caches (tests)."""
    global _cache, _last_success_at, _last_success_ids, _last_success_display
    global _synced_ids, _last_refresh, _warm_state, _warm_at
    _cache = None
    _last_success_at = None
    _last_success_ids = ()
    _last_success_display = {}
    _synced_ids = ()
    _last_refresh = 0.0
    _warm_state = None
    _warm_at = 0.0
    _runtime_outcomes.clear()
    from app.ai import kllm_cloud_client

    kllm_cloud_client.reset_runtime_state()


# Process-local runtime availability cache. Scope: one backend process. It is
# deliberately NOT shared across workers/VMs and is NOT persisted. TTL expiry
# allows recovery. A missing entry means "unknown" (never "ready").
_RUNTIME_SUCCESS_TTL_S = 600.0
_RUNTIME_UNAVAILABLE_TTL_S = 300.0
_runtime_outcomes: dict[str, tuple[str, float]] = {}


def runtime_state_for(model_id: str) -> str:
    entry = _runtime_outcomes.get(model_id)
    if not entry:
        return "unknown"
    state, expires_at = entry
    if time.monotonic() > expires_at:
        _runtime_outcomes.pop(model_id, None)
        return "unknown"
    return state


def record_runtime_outcome(
    model_id: str,
    *,
    succeeded: bool,
    model_specific_unavailable: bool = False,
) -> None:
    """Record a runtime outcome without touching approval or catalogue rows."""
    now = time.monotonic()
    if model_specific_unavailable:
        _runtime_outcomes[model_id] = (
            "temporarily_unavailable",
            now + _RUNTIME_UNAVAILABLE_TTL_S,
        )
    elif succeeded:
        _runtime_outcomes[model_id] = (
            "recently_responded",
            now + _RUNTIME_SUCCESS_TTL_S,
        )
    # Other outcomes (timeout, generic 5xx, network) leave state unchanged:
    # a timeout alone is not proof of model unavailability.


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def _get_sync_lock() -> asyncio.Lock:
    global _sync_lock
    if _sync_lock is None:
        _sync_lock = asyncio.Lock()
    return _sync_lock


async def _provider_row(db: AsyncSession):
    row = await provider_registry_service.get_by_slug(db, PROVIDER_SLUG)
    if row is None:
        row = await provider_registry_service.get_by_identifier(db, PROVIDER_SLUG)
    return row


async def is_enabled(db: AsyncSession) -> bool:
    """Both the runtime flag and the managed provider row must agree."""
    if not settings.KLLM_CLOUD_ENABLED:
        return False
    provider = await _provider_row(db)
    return bool(
        provider
        and provider.is_managed
        and provider.is_enabled
        and provider.status == "available"
    )

def _parse_catalog_ids(payload: dict[str, Any]) -> tuple[tuple[str, ...], dict[str, str]]:
    """Extract advertised ids from a ``/v1/models`` payload.

    Only ``id`` is used; anything the relay sends beyond it is ignored rather
    than trusted, and an id that is not a safe token is skipped.
    """
    data = payload.get("data")
    if not isinstance(data, list):
        raise KllmCloudProtocolError(
            "kLLM Cloud returned an unexpected catalogue response.",
            reason_code="invalid_catalog",
        )
    ids: list[str] = []
    display: dict[str, str] = {}
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id")
        if not isinstance(raw_id, str):
            continue
        model_id = raw_id.strip()
        if not catalog.is_valid_model_id(model_id) or model_id in seen:
            continue
        seen.add(model_id)
        ids.append(model_id)
        name = item.get("display_name")
        if isinstance(name, str) and name.strip():
            display[model_id] = name.strip()[:200]
    if not ids:
        raise KllmCloudProtocolError(
            "kLLM Cloud returned an empty catalogue.",
            reason_code="empty_catalog",
        )
    return tuple(ids), display


async def _read_raw(*, force: bool = False) -> _RawCatalog:
    """Fetch the catalogue with a short TTL; never raises for relay failures."""
    global _cache, _last_success_at, _last_success_ids, _last_success_display
    ttl = settings.KLLM_CLOUD_CATALOG_CACHE_TTL
    now = time.monotonic()
    if not force and _cache is not None and now - _cache.fetched_at < ttl:
        return _cache

    global _refresh_task
    if (
        not force
        and _cache is not None
        and _last_success_ids
        and (_refresh_task is None or _refresh_task.done())
    ):
        async def _bg_refresh():
            global _refresh_task
            try:
                await _read_raw(force=True)
            except Exception:
                pass
            finally:
                _refresh_task = None

        try:
            _refresh_task = asyncio.create_task(_bg_refresh())
        except RuntimeError:
            _refresh_task = None
        return _cache

    from app.ai import kllm_cloud_client

    client = kllm_cloud_client.kllm_cloud_client
    async with _get_lock():
        now = time.monotonic()
        if not force and _cache is not None and now - _cache.fetched_at < ttl:
            return _cache
        fetched_at_dt = datetime.now(UTC)
        if not client.is_configured():
            _cache = _RawCatalog(
                ok=False,
                ids=_last_success_ids,
                fetched_at=now,
                fetched_at_dt=fetched_at_dt,
                error_reason="not_configured",
                error_message="kLLM Cloud is not configured on this server.",
                relay_display=_last_success_display,
            )
            return _cache
        try:
            payload = await client.fetch_catalog()
            ids, display = _parse_catalog_ids(payload)
        except KllmCloudError as exc:
            logger.warning(
                "kllm_cloud_catalog_failed reason=%s",
                exc.reason_code or exc.code,
            )
            _cache = _RawCatalog(
                ok=False,
                ids=_last_success_ids,
                fetched_at=now,
                fetched_at_dt=fetched_at_dt,
                error_reason=exc.reason_code or exc.code,
                error_message=exc.message,
                relay_display=_last_success_display,
            )
            return _cache
        _last_success_at = fetched_at_dt
        _last_success_ids = ids
        _last_success_display = display
        _cache = _RawCatalog(
            ok=True,
            ids=ids,
            fetched_at=now,
            fetched_at_dt=fetched_at_dt,
            relay_display=display,
        )
        logger.info("kllm_cloud_catalog_ok models=%s", len(ids))
        return _cache


def _row_metadata(row: DiscoveredModel) -> dict[str, Any]:
    value = row.raw_metadata
    return value if isinstance(value, dict) else {}


def _descriptor(
    model_id: str,
) -> tuple[str, str | None, catalog.CuratedModel | None]:
    """Return ``(classification, canonical, curated entry)`` for one id."""
    kind = catalog.classify(model_id)
    canonical: str | None = None
    entry: catalog.CuratedModel | None = catalog.curated(model_id)
    if kind == "alias":
        canonical = catalog.alias_target(model_id)
        if canonical:
            entry = catalog.curated(canonical)
    elif kind in ("chat", "media"):
        canonical = model_id
    return kind, canonical, entry


def _catalog_session_factory():
    """Session factory used only for catalogue reconciliation.

    Imported lazily so importing this service does not depend on engine
    initialization order, and so tests can substitute a disposable session.
    """
    from app.db.session import AsyncSessionLocal

    return AsyncSessionLocal


async def _upsert_catalog_rows(db: AsyncSession, ids: tuple[str, ...]) -> None:
    """Apply the advertised set to one session (no commit, no deletions)."""
    result = await db.execute(
        select(DiscoveredModel).where(DiscoveredModel.provider_slug == PROVIDER_SLUG)
    )
    existing = {row.model_id: row for row in result.scalars().all()}
    now = datetime.now(UTC)
    for model_id in ids:
        kind, canonical, entry = _descriptor(model_id)
        display = catalog.display_name_for(model_id)
        metadata = {
            "classification": kind,
            "canonical": canonical,
            "source": "relay",
            "family": entry.family if entry else None,
            "vision": bool(entry and entry.vision),
            "tags": list(entry.tags) if entry else [],
        }
        row = existing.get(model_id)
        if row is None:
            db.add(
                DiscoveredModel(
                    provider_slug=PROVIDER_SLUG,
                    model_id=model_id,
                    display_name=display,
                    context_window=entry.context_window if entry else None,
                    description=entry.description if entry else None,
                    raw_metadata=metadata,
                    last_synced_at=now,
                )
            )
        else:
            row.display_name = display
            row.context_window = entry.context_window if entry else None
            row.description = entry.description if entry else None
            row.raw_metadata = metadata
            row.last_synced_at = now


async def _sync_catalog(ids: tuple[str, ...]) -> None:
    """Reconcile the advertised set in its own short-lived transaction.

    Catalogue discovery can be triggered from inside a request, so it must
    never commit or roll back that caller's session: pending approvals or
    chat writes may live in it. A separate session keeps the boundary
    explicit and contains a sync failure to the sync itself (the snapshot
    still reports the last known catalogue). ``_synced_ids`` only advances
    after a successful commit, so the next call retries. Concurrent callers
    are serialized and re-check the ids so the catalogue is not written twice.
    """
    global _synced_ids
    if _synced_ids == ids:
        return
    async with _get_sync_lock():
        if _synced_ids == ids:
            return
        factory = _catalog_session_factory()
        async with factory() as session:
            await _upsert_catalog_rows(session, ids)
            await session.commit()
        _synced_ids = ids


async def _load_rows(
    db: AsyncSession,
) -> tuple[list[DiscoveredModel], dict[str, ModelOverride]]:
    discovered = (
        await db.execute(
            select(DiscoveredModel)
            .where(DiscoveredModel.provider_slug == PROVIDER_SLUG)
            .order_by(DiscoveredModel.model_id)
        )
    ).scalars().all()
    rows = await model_overrides_service.list_rows(db, provider_slug=PROVIDER_SLUG)
    return list(discovered), {row.model_id: row for row in rows}

def _surface_readiness(
    *,
    enabled: bool,
    advertised: bool,
    relay_ok: bool,
    approved: bool,
    disabled: bool,
    kind: str,
    surface_enabled: bool,
    surface: str,
    runtime_state: str = "unknown",
) -> tuple[bool, str]:
    """Readiness for exactly one surface; never inferred from the other."""
    is_ready = bool(
        enabled
        and advertised
        and relay_ok
        and approved
        and not disabled
        and surface_enabled
        and kind == "chat"
        and runtime_state in ("ready", "recently_responded")
    )
    if disabled:
        reason = "model_disabled"
    elif not advertised:
        reason = "model_removed"
    elif not relay_ok:
        reason = "kllm_cloud_unreachable"
    elif kind != "chat":
        reason = "not_chat_" + kind
    elif not approved:
        reason = "not_approved"
    elif not surface_enabled:
        reason = surface + "_not_enabled"
    elif runtime_state == "checking":
        reason = "model_checking"
    elif runtime_state == "unavailable":
        reason = "model_unavailable"
    elif runtime_state in ("advertised", "unknown", "unverified"):
        reason = "model_unverified"
    elif is_ready:
        reason = "ready"
    else:
        reason = "kllm_cloud_disabled"
    return is_ready, reason


def surface_readiness(
    snapshot: CloudSnapshot, model: CloudModel, *, surface: str
) -> tuple[bool, str]:
    """Per-surface readiness for one snapshotted model.

    Chat and Review are independent: a model approved for one is not implied
    for the other, so callers that render both must ask for both.
    """
    if surface not in ("chat", "review"):
        raise ValueError("surface must be 'chat' or 'review'")
    return _surface_readiness(
        enabled=snapshot.enabled,
        advertised=model.available,
        relay_ok=snapshot.reachable,
        approved=model.approved,
        disabled=model.disabled,
        kind=model.kind,
        surface_enabled=(
            model.chat_enabled if surface == "chat" else model.review_enabled
        ),
        surface=surface,
        runtime_state=model.runtime_state,
    )


def _build_model(
    model_id: str,
    row: DiscoveredModel | None,
    override: ModelOverride | None,
    *,
    advertised: bool,
    relay_ok: bool,
    enabled: bool,
    surface: str,
) -> CloudModel:
    kind, canonical, entry = _descriptor(model_id)
    if kind == "unknown" and row is not None:
        metadata = _row_metadata(row)
        stored = metadata.get("classification")
        if isinstance(stored, str) and stored in ("chat", "swarm", "media", "alias"):
            kind = stored
        stored_canonical = metadata.get("canonical")
        if isinstance(stored_canonical, str):
            canonical = stored_canonical
    if entry is not None or kind != "unknown":
        display = catalog.display_name_for(model_id)
    else:
        display = row.display_name if row is not None else model_id
    approved = override is not None and override.status != "disabled"
    disabled = override is not None and override.status == "disabled"
    chat_enabled = True if override is None else bool(override.chat_enabled)
    review_enabled = True if override is None else bool(override.review_enabled)
    surface_enabled = chat_enabled if surface == "chat" else review_enabled
    r_state = runtime_state_for(model_id)
    ready, reason = _surface_readiness(
        enabled=enabled,
        advertised=advertised,
        relay_ok=relay_ok,
        approved=approved,
        disabled=disabled,
        kind=kind,
        surface_enabled=surface_enabled,
        surface=surface,
        runtime_state=r_state,
    )
    return CloudModel(
        model_id=model_id,
        display_name=display,
        kind=kind,
        family=entry.family if entry else None,
        context_window=entry.context_window if entry else None,
        vision=bool(entry and entry.vision),
        tags=tuple(entry.tags) if entry else (),
        description=entry.description if entry else None,
        canonical=canonical,
        approved=approved,
        disabled=disabled,
        chat_enabled=chat_enabled,
        review_enabled=review_enabled,
        available=advertised,
        ready=ready,
        reason_code=reason,
        runtime_state=runtime_state_for(model_id),
    )


async def get_snapshot(
    db: AsyncSession, *, force: bool = False, surface: str = "chat"
) -> CloudSnapshot:
    """Reconciled catalogue + provider state. Never raises for relay failure."""
    provider = await _provider_row(db)
    enabled = bool(
        settings.KLLM_CLOUD_ENABLED
        and provider
        and provider.is_managed
        and provider.is_enabled
        and provider.status == "available"
    )
    raw = await _read_raw(force=force)
    if raw.ok and raw.ids and _synced_ids != raw.ids:
        try:
            await _sync_catalog(raw.ids)
        except Exception as exc:  # pragma: no cover - defensive
            # The sync owns its session; the caller's transaction is never
            # rolled back or committed from here.
            logger.warning("kllm_cloud_sync_failed type=%s", type(exc).__name__)

    discovered, overrides = await _load_rows(db)
    rows_by_id = {row.model_id: row for row in discovered}
    advertised_ids = set(raw.ids)
    ordered: list[str] = list(raw.ids)
    ordered.extend(sorted(set(rows_by_id) - advertised_ids))
    ordered.extend(sorted(set(overrides) - set(ordered)))
    models = [
        _build_model(
            model_id,
            rows_by_id.get(model_id),
            overrides.get(model_id),
            advertised=model_id in advertised_ids,
            relay_ok=raw.ok,
            enabled=enabled,
            surface=surface,
        )
        for model_id in ordered
    ]
    counts = {
        "advertised": len(raw.ids),
        "canonical_chat": sum(
            1 for m in models if m.kind == "chat" and m.available
        ),
        "swarm": sum(1 for m in models if m.kind == "swarm" and m.available),
        "media": sum(1 for m in models if m.kind == "media" and m.available),
        "aliases": sum(1 for m in models if m.kind == "alias" and m.available),
        "unknown": sum(1 for m in models if m.kind == "unknown" and m.available),
        "approved": sum(1 for m in models if m.approved and not m.disabled),
        "chat_enabled": sum(
            1 for m in models if m.approved and not m.disabled and m.chat_enabled
        ),
        "review_enabled": sum(
            1 for m in models if m.approved and not m.disabled and m.review_enabled
        ),
        "pending": sum(
            1
            for m in models
            if m.kind == "chat" and not m.approved and not m.disabled
        ),
        "removed": sum(1 for m in models if not m.available),
        "disabled": sum(1 for m in models if m.disabled),
    }

    # Bounded background probe: probe at most one unprobed approved chat model
    # per snapshot refresh, rate-limited by cooldown and a single-slot
    # semaphore. Never blocks the snapshot response.
    if enabled and raw.ok:
        candidates = [
            m.model_id
            for m in models
            if m.kind == "chat"
            and m.approved
            and not m.disabled
            and m.available
            and m.runtime_state in ("advertised", "unknown")
        ]
        if candidates:
            first_candidate = candidates[0]
            now = time.monotonic()
            if now - _last_probe_attempt.get(first_candidate, 0.0) >= _PROBE_COOLDOWN_S:
                try:
                    asyncio.create_task(probe_model_readiness(first_candidate))
                except RuntimeError:
                    pass

    return CloudSnapshot(
        enabled=enabled,
        configured=is_configured(),
        reachable=raw.ok,
        stale=(not raw.ok) and bool(raw.ids),
        error=raw.error_message,
        error_reason=raw.error_reason,
        generated_at=datetime.now(UTC),
        fetched_at=raw.fetched_at,
        last_success_at=_last_success_at,
        catalog_ids=raw.ids,
        models=models,
        counts=counts,
        cache_ttl_s=settings.KLLM_CLOUD_CATALOG_CACHE_TTL,
    )


async def get_chat_models(db: AsyncSession) -> list[CloudModel]:
    snap = await get_snapshot(db, surface="chat")
    if not snap.enabled:
        return []
    return [
        m
        for m in snap.models
        if m.kind == "chat" and m.approved and not m.disabled and m.chat_enabled
    ]


async def get_review_models(db: AsyncSession) -> list[CloudModel]:
    snap = await get_snapshot(db, surface="review")
    if not snap.enabled:
        return []
    return [
        m
        for m in snap.models
        if m.kind == "chat" and m.approved and not m.disabled and m.review_enabled
    ]


async def model_options(
    db: AsyncSession, *, surface: str = "chat"
) -> list[dict[str, Any]]:
    """Selectable cloud models for pickers and routing.

    Shaped like ``kllm_service.get_model_options`` so a managed-provider
    caller can dispatch on the provider slug instead of guessing.
    Administrator-approved, non-disabled chat models whose *requested* surface
    is enabled are returned even when they have not yet been runtime-verified:
    the Review submission dropdown must let the operator select a Cloud model
    and let the actual review attempt verify it, rather than hiding it until a
    12-second probe happens to win a race against a >100-second Kaggle cold
    start. Readiness is reported honestly (``ready`` vs ``unverified``) so a
    client can label the model correctly. A disabled, unapproved, removed or
    unreachable provider yields an empty list, exactly like local kLLM.
    """
    if surface not in ("chat", "review"):
        raise ValueError("surface must be 'chat' or 'review'")
    snap = await get_snapshot(db, surface=surface)
    if not snap.enabled or not snap.reachable:
        return []
    surface_attr = "chat_enabled" if surface == "chat" else "review_enabled"
    stamp = snap.generated_at.isoformat()
    options: list[dict[str, Any]] = []
    for m in snap.models:
        if m.kind != "chat" or not m.approved or m.disabled or not m.available:
            continue
        if not getattr(m, surface_attr):
            continue
        options.append(
            {
                "model_name": m.key,
                "canonical_model_name": m.key,
                "model_id": m.model_id,
                "provider": PROVIDER_SLUG,
                "provider_name": PROVIDER_NAME,
                "litellm_model_name": f"{PROVIDER_SLUG}/{m.model_id}",
                "accessible": True,
                "admin_disabled": False,
                "deprecated": False,
                "preview": False,
                "experimental": False,
                "enterprise_only": False,
                "region_supported": True,
                "context_window": m.context_window,
                "input_cost": 0.0,
                "output_cost": 0.0,
                "supports_streaming": True,
                "supports_function_calling": True,
                "supports_vision": m.vision,
                "supports_reasoning": True,
                "status": "available",
                "readiness": "ready" if m.ready else "unverified",
                "reason_code": m.reason_code,
                "loads_on_demand": False,
                "validation_timestamp": stamp,
            }
        )
    return options


async def ensure_model_ready(
    db: AsyncSession, model: str, *, surface: str = "chat"
) -> CloudModel:
    """Final gate immediately before an inference call.

    Chat and Review each check their own surface flag, so a model approved for
    one is never implied for the other. A model the relay does not advertise is
    a definitive failure: it never falls back to another model.
    """
    if not await is_enabled(db):
        raise KllmCloudDisabledError(
            DISABLED_MESSAGE,
            reason_code="kllm_cloud_disabled",
            definitive=True,
        )
    # Strip the namespace without validating yet: an alias must produce its own
    # "not selectable" reason instead of a generic conversion error.
    key = model if is_cloud_key(model) else cloud_key(str(model or ""))
    model_id = key.split(":", 1)[1] if ":" in key else key
    if not catalog.is_canonical_chat(model_id):
        # Aliases and media IDs are advertised by the relay but are never
        # selectable here: a 400 is more honest than a silent substitution.
        if catalog.classify(model_id) == "alias":
            raise KllmCloudRequestError(
                "Compatibility aliases cannot be selected. Choose the model itself.",
                reason_code="alias_not_selectable",
                definitive=True,
            )
        raise KllmCloudRequestError(
            "This model cannot be selected in kLLM Cloud.",
            reason_code="model_not_selectable",
            definitive=True,
        )
    if not is_configured():
        raise KllmCloudNotConfiguredError(
            "kLLM Cloud is not available on this server.",
            reason_code="not_configured",
            definitive=True,
        )
    snap = await get_snapshot(db, surface=surface)
    if not snap.reachable:
        raise KllmCloudUnavailableError(
            "kLLM Cloud is temporarily unavailable. Please try again shortly.",
            reason_code=snap.error_reason or "relay_unreachable",
        )
    entry = next((m for m in snap.models if m.model_id == model_id), None)
    if entry is None or not entry.available:
        raise KllmCloudUnavailableError(
            "This model is no longer offered by kLLM Cloud.",
            reason_code="model_removed",
            definitive=True,
        )
    if entry.disabled:
        raise KllmCloudUnavailableError(
            "This model is temporarily disabled by an administrator.",
            reason_code="model_disabled",
            definitive=True,
        )
    if not entry.approved:
        surface_label = "Reviews" if surface == "review" else "Chat"
        raise KllmCloudNotApprovedError(
            f"This model is not available for {surface_label} in kLLM Cloud.",
            reason_code="not_approved",
            definitive=True,
        )
    if surface == "review" and not entry.review_enabled:
        raise KllmCloudSurfaceDisabledError(
            "This model is not available for Reviews in kLLM Cloud.",
            reason_code="review_not_enabled",
            definitive=True,
        )
    if surface != "review" and not entry.chat_enabled:
        raise KllmCloudSurfaceDisabledError(
            "This model is not available for Chat in kLLM Cloud.",
            reason_code="chat_not_enabled",
            definitive=True,
        )
    return replace(entry, ready=True, reason_code="ready")


# --- administrator operations (caller commits + audits) --------------------


async def set_approval(
    db: AsyncSession,
    model_id: str,
    approved: bool,
    *,
    chat_enabled: bool | None = None,
    review_enabled: bool | None = None,
    message: str | None = None,
) -> tuple[ModelOverride | None, str]:
    """Approve or revoke one canonical chat model (no commit).

    Approval keeps the ``model_overrides`` row with status ``available`` (the
    row *is* the approval record); revocation deletes it, returning the model to
    "pending", never to the provider default.
    """
    if not catalog.is_canonical_chat(model_id):
        raise KllmCloudInvalidModelError(
            "Only a canonical chat model can be approved for kLLM Cloud.",
            reason_code="model_not_selectable",
            definitive=True,
        )
    if not approved:
        row = await model_overrides_service.get_row(db, PROVIDER_SLUG, model_id)
        if row is None:
            return None, "noop"
        await db.delete(row)
        return row, "revoked"
    # A repeated approval (or a message-only call) is not a mutation: the
    # admin audit log must not record an action that changed nothing.
    existing = await model_overrides_service.get_row(db, PROVIDER_SLUG, model_id)
    if existing is not None and existing.status == "available":
        surfaces_match = (
            chat_enabled is None
            or bool(existing.chat_enabled) == bool(chat_enabled)
        ) and (
            review_enabled is None
            or bool(existing.review_enabled) == bool(review_enabled)
        )
        if surfaces_match:
            return existing, "noop"
    row, _action = await model_overrides_service.apply(
        db,
        provider_slug=PROVIDER_SLUG,
        model_id=model_id,
        status="available",
        message=message,
        keep_row=True,
        chat_enabled=chat_enabled,
        review_enabled=review_enabled,
    )
    return row, "approved"


async def set_disabled(
    db: AsyncSession, model_id: str, disabled: bool, *, message: str | None = None
) -> tuple[ModelOverride | None, str]:
    """Global per-model kill switch, shared with the existing admin surface."""
    if not catalog.is_canonical_chat(model_id):
        raise KllmCloudInvalidModelError(
            "Only a canonical chat model can be changed for kLLM Cloud.",
            reason_code="model_not_selectable",
            definitive=True,
        )
    existing = await model_overrides_service.get_row(db, PROVIDER_SLUG, model_id)
    if disabled:
        if existing is not None and existing.status == "disabled":
            return existing, "noop"
        row, action = await model_overrides_service.apply(
            db,
            provider_slug=PROVIDER_SLUG,
            model_id=model_id,
            status="disabled",
            message=message,
        )
        return row, ("disabled" if action != "noop" else "noop")
    if existing is None:
        return None, "noop"
    if existing.status == "available":
        return existing, "noop"
    row, _action = await model_overrides_service.apply(
        db,
        provider_slug=PROVIDER_SLUG,
        model_id=model_id,
        status="available",
        keep_row=True,
        message=message,
    )
    return row, "enabled"


async def set_surfaces(
    db: AsyncSession,
    model_id: str,
    *,
    chat_enabled: bool | None = None,
    review_enabled: bool | None = None,
) -> tuple[ModelOverride | None, str]:
    """Toggle the Chat/Review surface of an already-approved model (no commit)."""
    row = await model_overrides_service.get_row(db, PROVIDER_SLUG, model_id)
    if row is None or row.status == "disabled":
        raise KllmCloudInvalidModelError(
            "Approve this model before changing its surfaces.",
            reason_code="not_approved",
            definitive=True,
        )
    if (chat_enabled is None or bool(row.chat_enabled) == bool(chat_enabled)) and (
        review_enabled is None or bool(row.review_enabled) == bool(review_enabled)
    ):
        # Nothing changed: do not append a misleading mutation audit event.
        return row, "noop"
    row = await model_overrides_service.set_surfaces(
        db,
        row,
        chat_enabled=chat_enabled,
        review_enabled=review_enabled,
    )
    return row, "surfaces"


async def refresh_catalog(db: AsyncSession) -> dict[str, Any]:
    """Administrator-triggered refresh, rate limited to one per 10 seconds."""
    global _last_refresh
    now = time.monotonic()
    if _last_refresh and now - _last_refresh < REFRESH_MIN_INTERVAL_S:
        return {
            "refreshed": False,
            "throttled": True,
            "retry_after_seconds": round(
                REFRESH_MIN_INTERVAL_S - (now - _last_refresh), 1
            ),
        }
    _last_refresh = now
    snap = await get_snapshot(db, force=True)
    return {
        "refreshed": True,
        "throttled": False,
        "state": snap.state,
        "reason": snap.reason,
        "reachable": snap.reachable,
        "advertised": len(snap.catalog_ids),
        "last_success_at": (
            snap.last_success_at.isoformat() if snap.last_success_at else None
        ),
        "counts": snap.counts,
    }


async def probe_backend_warm(*, force: bool = False) -> dict[str, Any]:
    """``GET /health``: is *some* backend warm? Never per-model, never liveness."""
    global _warm_state, _warm_at
    now = time.monotonic()
    if (
        not force
        and _warm_state is not None
        and now - _warm_at < WARM_CACHE_TTL_S
    ):
        return _warm_state
    checked_at = datetime.now(UTC).isoformat()
    if not is_configured():
        _warm_state = {
            "state": "not_configured",
            "checked_at": checked_at,
            "detail": "kLLM Cloud is not configured on this server.",
        }
        _warm_at = now
        return _warm_state
    from app.ai import kllm_cloud_client

    try:
        status = await kllm_cloud_client.kllm_cloud_client.fetch_health()
    except KllmCloudError as exc:
        _warm_state = {
            "state": "unreachable",
            "checked_at": checked_at,
            "detail": exc.message,
        }
        _warm_at = now
        return _warm_state
    if status == 200:
        state = "warm"
        detail = "At least one model backend is warm and can serve requests."
    elif status == 503:
        state = "no_backend"
        detail = (
            "No model backend is warm right now. The provider itself is still "
            "reachable; a request may queue until a backend is ready."
        )
    elif status in (401, 403):
        state = "auth_rejected"
        detail = "The relay rejected the server credentials."
    else:
        state = "unknown"
        detail = "The relay answered the warm probe with an unexpected status."
    _warm_state = {"state": state, "checked_at": checked_at, "detail": detail}
    _warm_at = now
    return _warm_state


async def probe_model_readiness(model_id: str) -> dict[str, Any]:
    """Bounded one-shot readiness probe for a single canonical chat model.

    Sends a minimal streaming request (``Reply with exactly: RELAY_OK``,
    ``max_tokens=10``) and records the outcome. A completed stream marks the
    model ``recently_responded``; any timeout or error leaves the state
    unchanged (a probe failure is not proof of unavailability).

    At most one probe runs at a time, and each model is probed at most once
    per cooldown window. Never raises for relay failures.
    """
    from app.ai import kllm_cloud_client

    if not catalog.is_canonical_chat(model_id):
        return {"model_id": model_id, "skipped": "not_canonical_chat"}

    now = time.monotonic()
    last = _last_probe_attempt.get(model_id, 0.0)
    if now - last < _PROBE_COOLDOWN_S:
        return {
            "model_id": model_id,
            "skipped": "cooldown",
            "retry_after_seconds": round(_PROBE_COOLDOWN_S - (now - last), 1),
        }

    _last_probe_attempt[model_id] = now

    async with _get_probe_semaphore():
        try:
            async for item in kllm_cloud_client.kllm_cloud_client.stream(
                model_id,
                [{"role": "user", "content": "Reply with exactly: RELAY_OK"}],
                max_tokens=10,
            ):
                # Drain the stream; the client records the outcome in its
                # ``finally`` block based on whether a terminal marker was seen.
                pass
        except KllmCloudError:
            # The client already recorded the outcome (or didn't, for timeouts
            # and generic errors). Swallow: a probe failure is not an error.
            pass
        except Exception:
            pass

    state = runtime_state_for(model_id)
    return {"model_id": model_id, "runtime_state": state}


async def diagnostics(db: AsyncSession) -> dict[str, Any]:
    """Quota-free admin diagnostics. Never contains the URL or the key."""
    from app.ai import kllm_cloud_client

    snap = await get_snapshot(db)
    # Cached warm probe (15 s): one free ``GET /health`` at most, and never a
    # per-model claim - "warm" only means some backend can serve requests.
    warm = await probe_backend_warm()
    age = None
    if snap.fetched_at:
        age = round(max(0.0, time.monotonic() - snap.fetched_at), 1)
    return {
        "provider": PROVIDER_SLUG,
        "name": PROVIDER_NAME,
        "enabled": snap.enabled,
        "configured": snap.configured,
        "credential_configured": (
            kllm_cloud_client.kllm_cloud_client.credential_present()
        ),
        "reachable": snap.reachable,
        "stale": snap.stale,
        "state": snap.state,
        "reason": snap.reason,
        "error": snap.error,
        "error_reason": snap.error_reason,
        "last_success_at": (
            snap.last_success_at.isoformat() if snap.last_success_at else None
        ),
        "catalog_age_seconds": age,
        "cache_ttl_seconds": snap.cache_ttl_s,
        "concurrency_limit": settings.KLLM_CLOUD_CONCURRENCY_LIMIT,
        "queue_timeout_seconds": settings.KLLM_CLOUD_QUEUE_TIMEOUT_S,
        "counts": snap.counts,
        "overlay": catalog.counts(),
        "backend_warm": warm,
        "models": [m.as_admin_dict() for m in snap.models],
    }
