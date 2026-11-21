"""Managed local kLLM provider service.

kLLM owns serving, lifecycle, telemetry and inference. Revora only:

* reads kLLM's local admin/chat-ui state and normalizes it into strict,
  whitelisted DTOs (no account names, API keys, tunnel/LAN URLs, kernel
  references, raw prompts or scheduler internals);
* decides readiness for repository mapping and review execution;
* proxies a small, audited set of admin operations.

All network calls are server-side. The frontend never talks to kLLM.

Cache policy (protects the relay from the dashboard's polling):

* model/backend state: 15 s
* telemetry: 5 s (the caller only polls it while visible and active)

On a transient failure the last good state is served with ``stale=True`` and
an honest error string; nothing is fabricated when no state has ever been
read.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.provider_registry import provider_registry_service

logger = logging.getLogger(__name__)

KLLM_SLUG = "kllm"
STATE_TTL_SECONDS = 15.0
TELEMETRY_TTL_SECONDS = 5.0
STALE_AFTER_SECONDS = 30.0
#: kLLM's default `prelaunch_lead_seconds`. Used when a backend omits
#: `draining` but exposes `left_s`.
PRELAUNCH_LEAD_SECONDS = 1500

#: User-facing text for "kLLM is off" API errors. Deliberately free of
#: `backend/.env` paths, environment variable names and restart steps: those
#: are developer-facing and must never leak into user-facing UI messages.
DISABLED_MESSAGE = "kLLM is currently unavailable."

#: Mirrors kLLM `gateway/scheduler.py:UNIVERSAL_ALIASES` so a mapping saved
#: under an alias resolves to the same canonical model key the relay serves.
UNIVERSAL_ALIASES: dict[str, str] = {
    "nanbeige": "nanbeige4.3-33b-128k",
    "nanbeige-33b": "nanbeige4.3-33b-128k",
    "nanbeige-128k": "nanbeige4.3-33b-128k",
    "nanbeige4.3": "nanbeige4.3-33b-128k",
    "fable": "nanbeige4.3-33b-128k",
    "opus": "nanbeige4.3-33b-128k",
    "sonnet": "qwen3.8-27b",
    "haiku": "qwen3.8-27b",
    "qwen": "qwen3.8-27b",
    "qwen3.8": "qwen3.8-27b",
    "coder": "qwen3.8-27b",
    "256k": "qwen3.8-27b-256k",
    "long": "qwen3.8-27b-256k",
    "vision": "qwen3.8-27b-vision",
    "abliterated": "qwen3.8-27b-abliterated",
    "qwen3.8-abliterated-vision-256k": "qwen3.8-27b-vision-abliterated-256k",
    "qwen3.8-vision-abliterated-256k": "qwen3.8-27b-vision-abliterated-256k",
    "abliterated-vision-256k": "qwen3.8-27b-vision-abliterated-256k",
    "qwen3.8-27b-abliterated-vision-256k": "qwen3.8-27b-vision-abliterated-256k",
    "vision-abliterated-256k": "qwen3.8-27b-vision-abliterated-256k",
    "qwen3.8-27b-abliterated-vision": "qwen3.8-27b-vision-abliterated-256k",
    "qwen3.8-27b-vision-abliterated": "qwen3.8-27b-vision-abliterated-256k",
    "claude-3-opus": "nanbeige4.3-33b-128k",
    "claude-3-opus-20240229": "nanbeige4.3-33b-128k",
    "claude-opus-4-0": "nanbeige4.3-33b-128k",
    "claude-opus-4-1": "nanbeige4.3-33b-128k",
    "claude-opus-4-5": "nanbeige4.3-33b-128k",
    "claude-opus-4-6": "nanbeige4.3-33b-128k",
    "claude-opus-4-7": "nanbeige4.3-33b-128k",
    "claude-opus-4-8": "nanbeige4.3-33b-128k",
    "claude-opus-5": "nanbeige4.3-33b-128k",
    "claude-opus-5-5": "nanbeige4.3-33b-128k",
    "claude-fable-5": "nanbeige4.3-33b-128k",
    "claude-fable-5-1": "nanbeige4.3-33b-128k",
    "claude-3-5-sonnet": "qwen3.8-27b",
    "claude-3-5-sonnet-20241022": "qwen3.8-27b",
    "claude-3-5-sonnet-20240620": "qwen3.8-27b",
    "claude-3-7-sonnet": "qwen3.8-27b",
    "claude-3-7-sonnet-20250219": "qwen3.8-27b",
    "claude-sonnet-4": "qwen3.8-27b",
    "claude-sonnet-4-5": "qwen3.8-27b",
    "claude-sonnet-4-6": "qwen3.8-27b",
    "claude-sonnet-5": "qwen3.8-27b",
    "claude-sonnet-5-5": "qwen3.8-27b",
    "claude-3-haiku": "qwen3.8-27b",
    "claude-3-haiku-20240307": "qwen3.8-27b",
    "claude-3-5-haiku": "qwen3.8-27b",
    "claude-3-5-haiku-20241022": "qwen3.8-27b",
    "claude-haiku-4-5": "qwen3.8-27b",
    "claude-haiku-5-5": "qwen3.8-27b",
    "gpt-4o": "qwen3.8-27b-vision",
    "gpt-4o-mini": "qwen3.8-27b",
    "o1": "nanbeige4.3-33b-128k",
    "o3-mini": "nanbeige4.3-33b-128k",
}


class KllmError(Exception):
    """Base error with a safe, client-facing message.

    ``definitive`` marks a failure that cannot become usable by waiting:
    the mapped model is missing/failed, disabled, or explicitly not approved
    for on-demand loading. Transient transport/state failures leave it false
    so callers never trigger an automatic fallback from an ambiguous read.
    """

    code = "kllm_error"
    status_code = 502

    def __init__(
        self,
        message: str,
        *,
        definitive: bool = False,
        reason_code: str | None = None,
    ):
        self.message = message
        self.definitive = bool(definitive)
        self.reason_code = reason_code
        super().__init__(message)


class KllmDisabledError(KllmError):
    code = "kllm_disabled"
    status_code = 503


class KllmUnavailableError(KllmError):
    code = "kllm_unavailable"
    status_code = 503


class KllmNotConfiguredError(KllmError):
    code = "kllm_not_configured"
    status_code = 503


class KllmNotFoundError(KllmError):
    code = "kllm_not_found"
    status_code = 404


class KllmConflictError(KllmError):
    code = "kllm_conflict"
    status_code = 409


class KllmAuthError(KllmError):
    code = "kllm_auth_error"
    status_code = 502


@dataclass
class KllmModel:
    key: str
    status: str
    loaded: bool
    ready: bool
    context_window: int | None
    vision: bool
    tags: list[str] = field(default_factory=list)
    backend_count: int = 0
    #: Backend-computed, user-facing readiness projection. Raw kLLM status is
    #: preserved separately so the UI never has to interpret it itself.
    readiness: str = "unknown"
    reason_code: str = "unknown"

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "status": self.status,
            "loaded": self.loaded,
            "ready": self.ready,
            "readiness": self.readiness,
            "reason_code": self.reason_code,
            "context_window": self.context_window,
            "vision": self.vision,
            "tags": self.tags,
            "backend_count": self.backend_count,
        }


@dataclass
class KllmBackend:
    id: str
    model: str | None
    healthy: bool
    state: str
    up_s: int | None
    left_s: int | None
    draining: bool
    replaced_by: str | None
    sessions: int | None
    inflight: int | None
    idle_s: int | None
    errors_5m: int
    pinned: bool
    rpm: float | None
    quota_used_h: float | None
    quota_limit_h: float | None
    gpu: dict[str, Any] | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "model": self.model,
            "healthy": self.healthy,
            "state": self.state,
            "up_s": self.up_s,
            "left_s": self.left_s,
            "draining": self.draining,
            "replaced_by": self.replaced_by,
            "sessions": self.sessions,
            "inflight": self.inflight,
            "idle_s": self.idle_s,
            "errors_5m": self.errors_5m,
            "pinned": self.pinned,
            "rpm": self.rpm,
            "quota_used_h": self.quota_used_h,
            "quota_limit_h": self.quota_limit_h,
            "gpu": self.gpu,
        }


@dataclass
class KllmSnapshot:
    enabled: bool
    configured: bool
    reachable: bool
    stale: bool
    generated_at: datetime
    age_seconds: float
    error: str | None
    relay_health: dict[str, Any]
    models: list[KllmModel]
    backends: list[KllmBackend]
    pending: list[dict[str, Any]]
    summary: dict[str, Any]
    clients: list[dict[str, Any]]
    traffic: dict[str, Any]
    supervisor: bool
    autoscale: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "configured": self.configured,
            "reachable": self.reachable,
            "stale": self.stale,
            "generated_at": self.generated_at.isoformat(),
            "age_seconds": round(self.age_seconds, 1),
            "error": self.error,
            "relay_health": self.relay_health,
            "models": [m.as_dict() for m in self.models],
            "backends": [b.as_dict() for b in self.backends],
            "pending": self.pending,
            "summary": self.summary,
            "clients": self.clients,
            "traffic": self.traffic,
            "supervisor": self.supervisor,
            "autoscale": self.autoscale,
        }


@dataclass
class _RawState:
    fetched_at: float
    reachable: bool
    error: str | None
    models: dict[str, Any] | None
    backends: dict[str, Any] | None
    health: dict[str, Any] | None


# --- process-local caches (never persisted) --------------------------------
_raw_cache: _RawState | None = None
_telemetry_cache: dict[str, Any] | None = None
_telemetry_at: float = 0.0
_telemetry_error: str | None = None
# Opaque backend IDs: account name -> UUID and reverse. Never persisted and
# never exposed with the account name attached.
_backend_ids: dict[str, str] = {}
_backend_reverse: dict[str, str] = {}
_live_accounts: set[str] = set()


def _base_url() -> str:
    return settings.KLLM_SERVER_URL.rstrip("/")


def _is_management_access_allowed() -> bool:
    """Whether the configured kLLM endpoint is trusted for management reads.

    Loopback is always trusted (the default kLLM deployment). A non-loopback
    URL is trusted only when a server-side gateway key is configured: that key
    is explicitly documented for non-loopback deployments (e.g. Revora in a
    container reaching the host through a relay that rewrites ``Host`` to
    loopback). The key is never exposed to clients.
    """
    host = (urlparse(_base_url()).hostname or "").lower()
    if host in {"127.0.0.1", "localhost", "::1"}:
        return True
    return bool(settings.KLLM_GATEWAY_API_KEY)


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if settings.KLLM_GATEWAY_API_KEY:
        headers["Authorization"] = f"Bearer {settings.KLLM_GATEWAY_API_KEY}"
    return headers


def _post_headers() -> dict[str, str]:
    headers = _headers()
    headers["Content-Type"] = "application/json"
    # kLLM's admin router refuses state-changing requests without this header
    # (cross-site pages cannot set it without an ungranted CORS preflight).
    headers["X-Kllm-Panel"] = "1"
    return headers


def canonical_model(key: str | None) -> str:
    """Mirror kLLM's `_canonical_model` for the alias vocabulary we know."""
    value = (key or "").strip()
    value = value.removeprefix("openai/")
    seen: set[str] = set()
    while value not in seen:
        seen.add(value)
        target = UNIVERSAL_ALIASES.get(value)
        if not target or target == value:
            break
        value = target
    return value


def _opaque_id(account: str) -> str:
    value = _backend_ids.get(account)
    if value is None:
        value = str(uuid.uuid4())
        _backend_ids[account] = value
        _backend_reverse[value] = account
    return value


def resolve_backend_id(backend_id: str) -> str | None:
    """Resolve an opaque UUID to the live kLLM account name (server-side only)."""
    return _backend_reverse.get((backend_id or "").strip())


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _safe_error(exc: Exception | None, fallback: str) -> str:
    """Map transport/HTTP failures to a fixed, secret-free message."""
    if exc is None:
        return fallback
    if isinstance(exc, httpx.TimeoutException):
        return "kLLM request timed out."
    if isinstance(exc, httpx.HTTPError):
        return "kLLM is unreachable."
    return fallback


async def _fetch_json(
    path: str, *, timeout: float
) -> tuple[dict[str, Any] | None, str | None]:
    url = f"{_base_url()}{path}"
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.get(url, headers=_headers())
    except Exception as exc:
        logger.warning("kLLM GET %s failed: %s", path, type(exc).__name__)
        return None, _safe_error(exc, "kLLM is unreachable.")

    if response.status_code in (401, 403):
        return None, "kLLM rejected the server credentials."
    if response.status_code == 404:
        return None, "kLLM does not expose the requested management endpoint."
    if response.status_code >= 500:
        return None, "kLLM is temporarily unavailable."
    if response.status_code != 200:
        return None, f"kLLM returned HTTP {response.status_code}."
    try:
        data = response.json()
    except ValueError:
        return None, "kLLM returned an invalid response."
    if not isinstance(data, dict):
        return None, "kLLM returned an invalid response."
    return data, None


async def _post_json(
    path: str, payload: dict[str, Any], *, timeout: float = 15.0
) -> dict[str, Any]:
    url = f"{_base_url()}{path}"
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.post(url, json=payload, headers=_post_headers())
    except httpx.TimeoutException as exc:
        raise KllmUnavailableError("kLLM request timed out.") from exc
    except httpx.HTTPError as exc:
        raise KllmUnavailableError("kLLM is unreachable.") from exc
    except Exception as exc:
        logger.warning("kLLM POST %s failed: %s", path, type(exc).__name__)
        raise KllmUnavailableError("kLLM is unreachable.") from exc

    if response.status_code in (401, 403):
        raise KllmAuthError("kLLM rejected the server credentials.")
    if response.status_code == 404:
        raise KllmNotFoundError("kLLM could not find that resource.")
    if response.status_code == 409:
        raise KllmConflictError(
            "kLLM rejected the request because the resource is busy or paused."
        )
    if response.status_code >= 500:
        raise KllmUnavailableError("kLLM is temporarily unavailable.")
    if response.status_code not in (200, 202):
        raise KllmUnavailableError(
            f"kLLM returned HTTP {response.status_code}."
        )
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


async def _provider_row(db: AsyncSession):
    return await provider_registry_service.get_by_slug(db, KLLM_SLUG)


async def is_configured(db: AsyncSession) -> bool:
    provider = await _provider_row(db)
    return bool(provider and provider.is_managed)


async def is_enabled(db: AsyncSession) -> bool:
    """Both the runtime flag and the managed provider row must agree."""
    if not settings.KLLM_ENABLED:
        return False
    provider = await _provider_row(db)
    return bool(
        provider
        and provider.is_managed
        and provider.is_enabled
        and provider.status == "available"
    )


def invalidate_cache() -> None:
    global _raw_cache, _telemetry_cache, _telemetry_at, _telemetry_error
    _raw_cache = None
    _telemetry_cache = None
    _telemetry_at = 0.0
    _telemetry_error = None


async def _read_raw_state(force: bool = False) -> _RawState:
    global _raw_cache
    now = time.monotonic()
    if not force and _raw_cache is not None and now - _raw_cache.fetched_at < STATE_TTL_SECONDS:
        return _raw_cache

    if not _is_management_access_allowed():
        previous = _raw_cache
        error = (
            "kLLM management endpoints are local-only. Run Revora on the "
            "kLLM host (127.0.0.1) to use the dashboard."
        )
        if previous is not None:
            return _RawState(
                fetched_at=previous.fetched_at,
                reachable=previous.reachable,
                error=error,
                models=previous.models,
                backends=previous.backends,
                health=previous.health,
            )
        return _RawState(now, False, error, None, None, None)

    (models, models_err), (backends, backends_err), (health, health_err) = (
        await asyncio.gather(
            _fetch_json("/chat-ui/v1/models", timeout=settings.KLLM_STATE_TIMEOUT_S),
            _fetch_json("/admin/api/backends", timeout=settings.KLLM_STATE_TIMEOUT_S),
            _fetch_json("/__relay/health", timeout=settings.KLLM_STATE_TIMEOUT_S),
        )
    )
    reachable = models is not None and backends is not None
    error = None if reachable else (models_err or backends_err or health_err)
    state = _RawState(now, reachable, error, models, backends, health)
    if reachable:
        _raw_cache = state
        return state

    # Transient failure: serve the last good state as stale, never fabricate.
    if _raw_cache is not None:
        previous = _raw_cache
        return _RawState(
            fetched_at=previous.fetched_at,
            reachable=True,
            error=error,
            models=previous.models,
            backends=previous.backends,
            health=previous.health,
        )
    return state


def _backend_ready(backend: dict[str, Any], *, fresh: bool) -> bool:
    """Six-condition readiness for one backend (see plan)."""
    if not fresh:
        return False
    # 1/2: a backend row with a real URL is required (host is the sanitized
    # proxy for the URL in /admin/api/backends).
    if not backend.get("host"):
        return False
    # 3: explicit healthy=true; a missing value is not ready.
    if backend.get("healthy") is not True:
        return False
    # 4: draining / retiring backends are not ready.
    if backend.get("replaced_by"):
        return False
    left = backend.get("left_s")
    draining = backend.get("draining")
    if draining is None and isinstance(left, (int, float)):
        draining = left <= PRELAUNCH_LEAD_SECONDS
    return not draining


def _gpu_summary(res: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(res, dict):
        return None
    gpus = res.get("gpu") or []
    if not gpus:
        return None
    return {
        "count": len(gpus),
        "used_mib": res.get("gpu_used_mib"),
        "total_mib": res.get("gpu_total_mib"),
        "util": res.get("gpu_util"),
        "age_s": res.get("age_s"),
        "status": res.get("status"),
    }


def _readiness_projection(
    *,
    status: str,
    ready: bool,
    backend_count: int,
    reachable: bool,
    stale: bool,
    admin_disabled: bool,
) -> tuple[str, str]:
    """Map raw kLLM state to the user-facing readiness vocabulary.

    The projection is deliberately honest: a model reported ``loaded`` without
    a qualifying healthy backend is ``unavailable`` (not ready, and not a
    reason to issue another load), and stale/unreachable state is never ready.
    """
    if admin_disabled:
        return "unavailable", "admin_disabled"
    if not reachable:
        return "unavailable", "kllm_unreachable"
    if stale:
        return "stale", "kllm_state_stale"
    if status == "failed":
        return "failed", "model_failed"
    if status == "loading":
        return "loading", "model_loading"
    if ready:
        return "ready", "ready"
    if status == "loaded":
        return "unavailable", "no_ready_backend"
    if not backend_count and status not in ("unloaded",):
        return "unavailable", "model_unavailable"
    return "unloaded", "model_unloaded"


def _disabled_models_for(disabled: dict[str, set[str]]) -> set[str]:
    models: set[str] = set()
    for alias in (KLLM_SLUG, "kllm"):
        models.update(disabled.get(alias, set()))
    return models


def _build_snapshot(
    raw: _RawState,
    *,
    enabled: bool,
    configured: bool,
    disabled_models: set[str],
) -> KllmSnapshot:
    now = time.monotonic()
    age = max(0.0, now - raw.fetched_at)
    stale = not raw.reachable or raw.error is not None or age > STALE_AFTER_SECONDS
    fresh = raw.reachable and not stale

    backends_payload = (raw.backends or {}).get("backends") or []
    if not isinstance(backends_payload, list):
        backends_payload = []

    _live_accounts.clear()
    backends: list[KllmBackend] = []
    for row in backends_payload:
        if not isinstance(row, dict):
            continue
        account = str(row.get("account") or "")
        if not account:
            continue
        _live_accounts.add(account)
        left = row.get("left_s")
        draining = row.get("draining")
        if draining is None and isinstance(left, (int, float)):
            draining = left <= PRELAUNCH_LEAD_SECONDS
        replaced_by = row.get("replaced_by")
        healthy = row.get("healthy") is True
        if replaced_by:
            state = "retiring"
        elif draining:
            state = "draining"
        elif not healthy:
            state = "unhealthy"
        else:
            state = "running"
        backends.append(
            KllmBackend(
                id=_opaque_id(account),
                model=canonical_model(row.get("model_key")) or None,
                healthy=healthy,
                state=state,
                up_s=row.get("up_s"),
                left_s=left,
                draining=bool(draining),
                replaced_by=(
                    _opaque_id(str(replaced_by)) if replaced_by else None
                ),
                sessions=row.get("sessions"),
                inflight=row.get("inflight"),
                idle_s=row.get("idle_s"),
                errors_5m=int(row.get("errors_5m") or 0),
                pinned=bool(row.get("pinned")),
                rpm=row.get("rpm"),
                quota_used_h=row.get("quota_used_h"),
                quota_limit_h=row.get("quota_limit_h"),
                gpu=_gpu_summary(row.get("res")),
            )
        )

    # Index ready backends by canonical model key.
    ready_by_model: dict[str, int] = {}
    for row in backends_payload:
        if not isinstance(row, dict):
            continue
        if not _backend_ready(row, fresh=fresh):
            continue
        key = canonical_model(row.get("model_key"))
        if key:
            ready_by_model[key] = ready_by_model.get(key, 0) + 1

    models_payload = (raw.models or {}).get("data") or []
    if not isinstance(models_payload, list):
        models_payload = []
    models: list[KllmModel] = []
    for row in models_payload:
        if not isinstance(row, dict):
            continue
        key = canonical_model(row.get("id") or row.get("model"))
        if not key:
            continue
        status_obj = row.get("status")
        status = (
            str(status_obj.get("value"))
            if isinstance(status_obj, dict)
            else str(status_obj or "unloaded")
        )
        architecture = row.get("architecture") or {}
        modalities = architecture.get("input_modalities") or []
        tags = [str(t) for t in (row.get("tags") or [])]
        vision = "image" in modalities or "vision" in {t.lower() for t in tags}
        backend_count = ready_by_model.get(key, 0)
        loaded = status == "loaded"
        admin_disabled = key in disabled_models
        ready = loaded and backend_count > 0 and not admin_disabled
        readiness, reason_code = _readiness_projection(
            status=status,
            ready=ready,
            backend_count=backend_count,
            reachable=raw.reachable,
            stale=stale,
            admin_disabled=admin_disabled,
        )
        models.append(
            KllmModel(
                key=key,
                status=status,
                loaded=loaded,
                ready=ready,
                context_window=row.get("context_length"),
                vision=vision,
                tags=tags,
                backend_count=backend_count,
                readiness=readiness,
                reason_code=reason_code,
            )
        )

    pending_payload = (raw.backends or {}).get("pending") or []
    if not isinstance(pending_payload, list):
        pending_payload = []
    pending: list[dict[str, Any]] = []
    for row in pending_payload:
        if not isinstance(row, dict):
            continue
        account = str(row.get("account") or "")
        if not account:
            continue
        pending.append(
            {
                "id": _opaque_id(account),
                "model": canonical_model(row.get("model_key")) or None,
                "phase": str(row.get("phase") or "starting")[:40],
                "failed": bool(row.get("failed")),
                "age_s": row.get("age_s"),
            }
        )

    health_payload = raw.health or {}
    relay_health = {
        "ok": bool(health_payload.get("ok")),
        "inflight": int(health_payload.get("inflight") or 0),
    }

    summary = {
        "backends": len(backends),
        "healthy_backends": sum(1 for b in backends if b.healthy),
        "running_backends": sum(1 for b in backends if b.state == "running"),
        "draining_backends": sum(1 for b in backends if b.draining),
        "pinned_backends": sum(1 for b in backends if b.pinned),
        "sessions": sum(int(b.sessions or 0) for b in backends),
        "inflight": sum(int(b.inflight or 0) for b in backends),
        "loaded_models": sum(1 for m in models if m.loaded),
        "ready_models": sum(1 for m in models if m.ready),
        "loading_models": sum(1 for m in models if m.status == "loading"),
        "failed_models": sum(1 for m in models if m.status == "failed"),
        "pending_backends": len(pending),
    }

    clients_payload = (raw.backends or {}).get("clients") or []
    clients: list[dict[str, Any]] = []
    if isinstance(clients_payload, list):
        for row in clients_payload:
            if not isinstance(row, dict):
                continue
            clients.append(
                {
                    "kind": str(row.get("kind") or "API")[:40],
                    "sessions": int(row.get("sessions") or 0),
                    "rpm": row.get("rpm"),
                }
            )

    traffic_payload = (raw.backends or {}).get("traffic") or {}
    traffic = {
        "rpm": traffic_payload.get("rpm"),
        "ttft_p50": traffic_payload.get("ttft_p50"),
    }

    generated_at = datetime.fromtimestamp(time.time() - age, tz=UTC)

    return KllmSnapshot(
        enabled=enabled,
        configured=configured,
        reachable=raw.reachable,
        stale=stale,
        generated_at=generated_at,
        age_seconds=age,
        error=raw.error,
        relay_health=relay_health,
        models=models,
        backends=backends,
        pending=pending,
        summary=summary,
        clients=clients,
        traffic=traffic,
        supervisor=bool((raw.backends or {}).get("supervisor")),
        autoscale=bool((raw.backends or {}).get("autoscale")),
    )


async def get_snapshot(db: AsyncSession, *, force: bool = False) -> KllmSnapshot:
    configured = await is_configured(db)
    enabled = await is_enabled(db)
    if not enabled:
        return KllmSnapshot(
            enabled=False,
            configured=configured,
            reachable=False,
            stale=False,
            generated_at=datetime.now(UTC),
            age_seconds=0.0,
            error=None,
            relay_health={"ok": False, "inflight": 0},
            models=[],
            backends=[],
            pending=[],
            summary={
                "backends": 0,
                "healthy_backends": 0,
                "running_backends": 0,
                "draining_backends": 0,
                "pinned_backends": 0,
                "sessions": 0,
                "inflight": 0,
                "loaded_models": 0,
                "ready_models": 0,
                "loading_models": 0,
                "failed_models": 0,
                "pending_backends": 0,
            },
            clients=[],
            traffic={"rpm": None, "ttft_p50": None},
            supervisor=False,
            autoscale=False,
        )

    raw = await _read_raw_state(force=force)
    disabled: set[str] = set()
    if raw.reachable:
        from app.services.model_overrides import model_overrides_service

        disabled = _disabled_models_for(await model_overrides_service.get_disabled_map(db))
    return _build_snapshot(
        raw, enabled=True, configured=configured, disabled_models=disabled
    )


async def get_ready_models(db: AsyncSession) -> list[KllmModel]:
    snapshot = await get_snapshot(db)
    if not snapshot.enabled or not snapshot.reachable:
        return []
    return [m for m in snapshot.models if m.ready]


async def ensure_model_available(db: AsyncSession, model: str) -> KllmModel:
    """Selection-time validation: the model exists and may be used.

    Unlike :func:`ensure_model_ready`, an unloaded model is *available*: the
    administrator may have approved on-demand loading. This function never
    substitutes another model and never forces a load.
    """
    if not settings.KLLM_ENABLED:
        raise KllmDisabledError(
            DISABLED_MESSAGE
        )
    provider = await _provider_row(db)
    if provider is None or not provider.is_managed:
        raise KllmNotConfiguredError(
            "The kLLM managed provider is not configured.", definitive=True
        )
    if not provider.is_enabled or provider.status != "available":
        raise KllmDisabledError(
            provider.status_message
            or "The kLLM managed provider is currently disabled.",
            definitive=True,
        )

    canonical = canonical_model(model)
    if not canonical:
        raise KllmUnavailableError(
            "A kLLM model must be selected.", definitive=True
        )

    from app.services.model_overrides import model_overrides_service

    if await model_overrides_service.is_model_disabled(db, KLLM_SLUG, canonical):
        raise KllmUnavailableError(
            f"Model '{canonical}' is temporarily disabled by an administrator.",
            definitive=True,
        )

    # Selection is a preflight decision. Read kLLM's current state instead of
    # relying on the dashboard cache so a just-unloaded or just-disabled model
    # cannot enter an execution snapshot from stale state.
    snapshot = await get_snapshot(db, force=True)
    if not snapshot.reachable:
        raise KllmUnavailableError(
            snapshot.error or "kLLM is unreachable. The model cannot be verified."
        )
    if snapshot.stale:
        raise KllmUnavailableError(
            "kLLM state is stale; the model cannot be verified right now."
        )
    match = next((m for m in snapshot.models if m.key == canonical), None)
    if match is None:
        raise KllmUnavailableError(
            f"Model '{canonical}' is not available in kLLM.", definitive=True
        )
    if match.readiness == "stale":
        raise KllmUnavailableError(
            "kLLM state is stale; the model cannot be verified right now."
        )
    if match.readiness == "unavailable":
        reason = match.reason_code
        transient = reason == "kllm_unreachable"
        raise KllmUnavailableError(
            f"Model '{canonical}' is not available in kLLM right now.",
            definitive=not transient,
        )
    return match


async def ensure_model_ready(
    db: AsyncSession, model: str, *, force: bool = False
) -> KllmModel:
    """Execution/mapping-time validation. Never substitutes another model."""
    if not settings.KLLM_ENABLED:
        raise KllmDisabledError(
            DISABLED_MESSAGE
        )
    provider = await _provider_row(db)
    if provider is None or not provider.is_managed:
        raise KllmNotConfiguredError("The kLLM managed provider is not configured.")
    if not provider.is_enabled or provider.status != "available":
        raise KllmDisabledError(
            provider.status_message
            or "The kLLM managed provider is currently disabled."
        )

    canonical = canonical_model(model)
    if not canonical:
        raise KllmUnavailableError("A kLLM model must be selected.")

    from app.services.model_overrides import model_overrides_service

    if await model_overrides_service.is_model_disabled(db, KLLM_SLUG, canonical):
        raise KllmUnavailableError(
            f"Model '{canonical}' is temporarily disabled by an administrator."
        )

    snapshot = await get_snapshot(db, force=force)
    if not snapshot.reachable:
        raise KllmUnavailableError(
            snapshot.error or "kLLM is unreachable. The model cannot be verified."
        )
    if snapshot.stale:
        raise KllmUnavailableError(
            "kLLM state is stale; the model cannot be verified right now."
        )
    match = next((m for m in snapshot.models if m.key == canonical), None)
    if match is None:
        raise KllmUnavailableError(
            f"Model '{canonical}' is not available in kLLM."
        )
    if not match.ready:
        if match.status == "loading":
            raise KllmUnavailableError(
                f"Model '{canonical}' is still loading in kLLM."
            )
        if match.status == "failed":
            raise KllmUnavailableError(
                f"Model '{canonical}' failed to load in kLLM."
            )
        if match.status == "loaded":
            raise KllmUnavailableError(
                f"Model '{canonical}' has no healthy backend in kLLM."
            )
        raise KllmUnavailableError(
            f"Model '{canonical}' is not loaded and ready in kLLM."
        )
    return match


async def ensure_model_selectable(db: AsyncSession, model: str) -> KllmModel:
    """Execution-selection gate for a managed model.

    A ready model passes. A loading model passes (execution waits for it). An
    unloaded model passes only when the administrator enabled review-demand
    loading for that exact model; otherwise it is a definitive failure so an
    explicitly opted-in fallback may be used.
    """
    match = await ensure_model_available(db, model)
    if match.ready or match.status == "loading":
        return match
    if match.status == "unloaded":
        from app.services import kllm_autoload

        policy = await kllm_autoload.get_policy(db, force=True)
        if kllm_autoload.review_allows(policy, match.key):
            return match
        raise KllmUnavailableError(
            f"Model '{match.key}' is not loaded and automatic loading is not "
            "enabled for this model by an administrator.",
            definitive=True,
        )
    if match.status == "failed":
        raise KllmUnavailableError(
            f"Model '{match.key}' failed to load in kLLM.", definitive=True
        )
    raise KllmUnavailableError(
        f"Model '{match.key}' is not selectable in kLLM right now."
    )


async def get_telemetry(db: AsyncSession, *, force: bool = False) -> dict[str, Any]:
    """Aggregate live GPU/session telemetry. No account names or URLs."""
    global _telemetry_cache, _telemetry_at, _telemetry_error
    if not await is_enabled(db):
        raise KllmDisabledError(
            DISABLED_MESSAGE
        )

    now = time.monotonic()
    if (
        not force
        and _telemetry_cache is not None
        and now - _telemetry_at < TELEMETRY_TTL_SECONDS
    ):
        return _telemetry_cache

    if not _is_management_access_allowed():
        return {
            "available": False,
            "stale": False,
            "generated_at": _now_iso(),
            "age_seconds": 0.0,
            "error": (
                "kLLM telemetry is local-only. Run Revora on the kLLM host "
                "(127.0.0.1) to read it."
            ),
            "reason": "local_only",
            "gpus": [],
            "backends": [],
            "totals": {
                "gpu_used_mib": 0,
                "gpu_total_mib": 0,
                "gpu_util": None,
                "backends": 0,
                "sessions": 0,
                "inflight": 0,
                "rpm": 0,
            },
        }

    data, error = await _fetch_json(
        "/admin/api/backends", timeout=settings.KLLM_TELEMETRY_TIMEOUT_S
    )
    if data is None:
        _telemetry_error = error or "kLLM telemetry is unavailable."
        if _telemetry_cache is not None:
            stale = dict(_telemetry_cache)
            stale["stale"] = True
            stale["error"] = _telemetry_error
            stale["age_seconds"] = round(now - _telemetry_at, 1)
            return stale
        return {
            "available": False,
            "stale": False,
            "generated_at": _now_iso(),
            "age_seconds": 0.0,
            "error": _telemetry_error,
            "reason": "unavailable",
            "gpus": [],
            "backends": [],
            "totals": {
                "gpu_used_mib": 0,
                "gpu_total_mib": 0,
                "gpu_util": None,
                "backends": 0,
                "sessions": 0,
                "inflight": 0,
                "rpm": 0,
            },
        }

    rows = data.get("backends") or []
    active = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("healthy") is True
        and not row.get("replaced_by")
    ]
    if not active:
        result = {
            "available": False,
            "stale": False,
            "generated_at": _now_iso(),
            "age_seconds": 0.0,
            "error": None,
            "reason": "no_active_backends",
            "gpus": [],
            "backends": [],
            "totals": {
                "gpu_used_mib": 0,
                "gpu_total_mib": 0,
                "gpu_util": None,
                "backends": 0,
                "sessions": 0,
                "inflight": 0,
                "rpm": 0,
            },
        }
        _telemetry_cache = result
        _telemetry_at = now
        _telemetry_error = None
        return result

    gpus: list[dict[str, Any]] = []
    backend_rows: list[dict[str, Any]] = []
    used_total = 0
    size_total = 0
    util_values: list[float] = []
    sessions_total = 0
    inflight_total = 0
    rpm_total = 0.0
    for row in active:
        account = str(row.get("account") or "")
        res = row.get("res") or {}
        row_gpus = res.get("gpu") or []
        for gpu in row_gpus:
            if not isinstance(gpu, dict):
                continue
            gpus.append(
                {
                    "index": gpu.get("i"),
                    "used_mib": gpu.get("used_mib"),
                    "total_mib": gpu.get("total_mib"),
                    "util": gpu.get("util"),
                    "temp": gpu.get("temp"),
                }
            )
        used = int(res.get("gpu_used_mib") or 0)
        size = int(res.get("gpu_total_mib") or 0)
        util = res.get("gpu_util")
        used_total += used
        size_total += size
        if isinstance(util, (int, float)):
            util_values.append(float(util))
        sessions = int(row.get("sessions") or 0)
        inflight = int(row.get("inflight") or 0)
        rpm = float(row.get("rpm") or 0.0)
        sessions_total += sessions
        inflight_total += inflight
        rpm_total += rpm
        backend_rows.append(
            {
                "id": _opaque_id(account),
                "model": canonical_model(row.get("model_key")) or None,
                "gpu_used_mib": res.get("gpu_used_mib"),
                "gpu_total_mib": res.get("gpu_total_mib"),
                "gpu_util": util,
                "sessions": sessions,
                "inflight": inflight,
                "rpm": row.get("rpm"),
            }
        )

    result = {
        "available": True,
        "stale": False,
        "generated_at": _now_iso(),
        "age_seconds": 0.0,
        "error": None,
        "reason": None,
        "gpus": gpus,
        "backends": backend_rows,
        "totals": {
            "gpu_used_mib": used_total,
            "gpu_total_mib": size_total,
            "gpu_util": (
                round(sum(util_values) / len(util_values)) if util_values else None
            ),
            "backends": len(active),
            "sessions": sessions_total,
            "inflight": inflight_total,
            "rpm": round(rpm_total, 2),
        },
    }
    _telemetry_cache = result
    _telemetry_at = now
    _telemetry_error = None
    return result


# --- admin operations ------------------------------------------------------


def _require_confirm(confirm: bool) -> None:
    if not confirm:
        raise KllmConflictError(
            "This action requires explicit confirmation."
        )


def _live_backend(backend_id: str, snapshot: KllmSnapshot) -> KllmBackend | None:
    return next((b for b in snapshot.backends if b.id == backend_id), None)


async def request_model_load(db: AsyncSession, model: str) -> dict[str, Any]:
    """Issue at most one upstream load request for an exact canonical model.

    Used by the automatic-loading paths. It never substitutes a model and
    never retries: kLLM's load endpoint is idempotent for loaded/loading
    models and returns 409 for paused/failed ones.
    """
    if not await is_enabled(db):
        raise KllmDisabledError(
            DISABLED_MESSAGE
        )
    canonical = canonical_model(model)
    if not canonical:
        raise KllmUnavailableError("A kLLM model must be selected.")

    from app.services.model_overrides import model_overrides_service

    if await model_overrides_service.is_model_disabled(db, KLLM_SLUG, canonical):
        raise KllmConflictError(
            f"Model '{canonical}' is disabled by an administrator.",
            definitive=True,
            reason_code="admin_disabled",
        )

    snapshot = await get_snapshot(db, force=True)
    if not snapshot.reachable:
        raise KllmUnavailableError(
            snapshot.error or "kLLM is unreachable. The model cannot be loaded."
        )
    if snapshot.stale:
        raise KllmUnavailableError(
            "kLLM state is stale; the model cannot be loaded safely right now."
        )
    existing = next((m for m in snapshot.models if m.key == canonical), None)
    if existing is None:
        raise KllmNotFoundError(f"Model '{canonical}' is not in kLLM's catalogue.")
    if existing.ready:
        return {"status": "already_loaded", "model": canonical}
    if existing.status == "loading":
        return {"status": "already_loading", "model": canonical}
    if existing.status == "failed":
        raise KllmConflictError(
            f"Model '{canonical}' is paused after a failed load in kLLM."
        )

    # kLLM's ``/chat-ui/models/load`` endpoint is a no-op: since 2026-11-10 it
    # merely acknowledges a model pick and never launches a kernel (a model
    # starts on its first message via autoscale, or through this admin endpoint).
    # The only server-side endpoint that actually starts a backend is
    # ``/admin/api/backends/launch``, which takes the exact model key and lets
    # kLLM choose the next free account. It is a guarded admin route, so the
    # same panel header/credentials used by the other admin POSTs are sent.
    await _post_json("/admin/api/backends/launch", {"model": canonical})
    invalidate_cache()
    return {"status": "loading", "model": canonical}


async def load_model(
    db: AsyncSession, model: str, *, confirm: bool = False
) -> dict[str, Any]:
    canonical = canonical_model(model)
    if not canonical:
        raise KllmUnavailableError("A kLLM model must be selected.")
    _require_confirm(confirm)
    return await request_model_load(db, canonical)


async def stop_backend(
    db: AsyncSession,
    backend_id: str,
    *,
    confirm: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    if not await is_enabled(db):
        raise KllmDisabledError(
            DISABLED_MESSAGE
        )
    _require_confirm(confirm)
    account = resolve_backend_id(backend_id)
    if account is None:
        raise KllmNotFoundError("Unknown kLLM backend.")

    snapshot = await get_snapshot(db, force=True)
    live = _live_backend(backend_id, snapshot)
    if live is None:
        return {"status": "already_stopped", "models_affected": []}

    sessions = int(live.sessions or 0)
    inflight = int(live.inflight or 0)
    if (sessions or inflight) and not force:
        raise KllmConflictError(
            "This backend is serving active sessions or in-flight requests. "
            "kLLM provides no drain guarantee; repeat with force=true to stop it."
        )

    affected = sorted({b.model for b in snapshot.backends if b.id == backend_id and b.model})
    await _post_json("/admin/api/backends/stop", {"account": account})
    invalidate_cache()
    return {
        "status": "stopping",
        "models_affected": affected,
        "sessions_affected": sessions,
        "inflight_affected": inflight,
    }


async def unload_model(
    db: AsyncSession,
    model: str,
    *,
    confirm: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Unload an exact model by stopping every backend and pending launch.

    kLLM's ``/chat-ui/models/unload`` endpoint is a verified no-op, so this
    composes the only destructive mechanism kLLM actually provides: per-account
    backend stop. No stop request is ever retried.
    """
    if not await is_enabled(db):
        raise KllmDisabledError(
            DISABLED_MESSAGE
        )
    canonical = canonical_model(model)
    if not canonical:
        raise KllmUnavailableError("A kLLM model must be selected.")
    _require_confirm(confirm)

    snapshot = await get_snapshot(db, force=True)
    if not snapshot.reachable:
        raise KllmUnavailableError(
            snapshot.error or "kLLM is unreachable. The model cannot be unloaded."
        )
    if snapshot.stale:
        raise KllmUnavailableError(
            "kLLM state is stale; the model cannot be unloaded safely right now."
        )

    running = [b for b in snapshot.backends if b.model == canonical]
    pending = [p for p in snapshot.pending if p.get("model") == canonical]
    sessions = sum(int(b.sessions or 0) for b in running)
    inflight = sum(int(b.inflight or 0) for b in running)
    if (sessions or inflight) and not force:
        raise KllmConflictError(
            "Model "
            f"'{canonical}' is serving {sessions} session(s) and {inflight} "
            "in-flight request(s). kLLM provides no drain guarantee; repeat "
            "with force=true to stop the serving backends."
        )

    seen: set[str] = set()
    running_accounts: list[str] = []
    for backend in running:
        account = resolve_backend_id(backend.id)
        if account and account not in seen:
            seen.add(account)
            running_accounts.append(account)
    pending_accounts: list[str] = []
    for row in pending:
        account = resolve_backend_id(str(row.get("id") or ""))
        if account and account not in seen:
            seen.add(account)
            pending_accounts.append(account)

    if not running_accounts and not pending_accounts:
        return {
            "status": "already_unloaded",
            "model": canonical,
            "stopped": 0,
            "pending_stopped": 0,
            "sessions_affected": sessions,
            "inflight_affected": inflight,
        }

    stopped_running = 0
    stopped_pending = 0
    errors = 0
    for account in running_accounts:
        try:
            await _post_json("/admin/api/backends/stop", {"account": account})
            stopped_running += 1
        except KllmError:
            # Never retry a stop: one request per target, then report honestly.
            errors += 1
    for account in pending_accounts:
        try:
            await _post_json("/admin/api/backends/stop", {"account": account})
            stopped_pending += 1
        except KllmError:
            errors += 1

    invalidate_cache()
    fresh = await get_snapshot(db, force=True)
    remaining = [b for b in fresh.backends if b.model == canonical]
    remaining_pending = [p for p in fresh.pending if p.get("model") == canonical]

    if not fresh.reachable or fresh.stale:
        status = "ambiguous"
    elif remaining or remaining_pending:
        status = (
            "partial"
            if (stopped_running or stopped_pending)
            else "ambiguous"
        )
    else:
        status = "success"

    return {
        "status": status,
        "model": canonical,
        "stopped": stopped_running,
        "pending_stopped": stopped_pending,
        "targets": len(running_accounts) + len(pending_accounts),
        "remaining_backends": len(remaining),
        "remaining_pending": len(remaining_pending),
        "sessions_affected": sessions,
        "inflight_affected": inflight,
        "errors": errors,
    }


async def rotate_backend(
    db: AsyncSession, backend_id: str, *, confirm: bool = False
) -> dict[str, Any]:
    if not await is_enabled(db):
        raise KllmDisabledError(
            DISABLED_MESSAGE
        )
    _require_confirm(confirm)
    account = resolve_backend_id(backend_id)
    if account is None:
        raise KllmNotFoundError("Unknown kLLM backend.")

    snapshot = await get_snapshot(db, force=True)
    live = _live_backend(backend_id, snapshot)
    if live is None:
        raise KllmConflictError("That kLLM backend is no longer running.")
    await _post_json(
        "/admin/api/backends/rotate",
        {"account": account, "model": live.model},
    )
    invalidate_cache()
    return {"status": "rotating", "model": live.model}


async def pin_backend(
    db: AsyncSession, backend_id: str, *, pinned: bool = True
) -> dict[str, Any]:
    if not await is_enabled(db):
        raise KllmDisabledError(
            DISABLED_MESSAGE
        )
    account = resolve_backend_id(backend_id)
    if account is None:
        raise KllmNotFoundError("Unknown kLLM backend.")

    snapshot = await get_snapshot(db, force=True)
    if _live_backend(backend_id, snapshot) is None:
        raise KllmNotFoundError("That kLLM backend is no longer running.")
    await _post_json(
        "/admin/api/backends/pin", {"account": account, "pinned": bool(pinned)}
    )
    invalidate_cache()
    return {"status": "pinned" if pinned else "unpinned"}


async def get_default_model(db: AsyncSession) -> str | None:
    """The kLLM default model, which is the only always-on-eligible model."""
    try:
        provider = await _provider_row(db)
    except Exception:
        return None
    if provider is None:
        return None
    return canonical_model(provider.default_model) or None


async def get_autoscale_config() -> dict[str, Any]:
    """Read the effective always-on size without exposing scheduler internals.

    kLLM exposes both the legacy ``desired_pool`` and the newer
    ``autoscale.min_backends``. Either can enable an always-on default model, so
    the effective size is their maximum. The raw knobs are returned only as
    normalized counts; no scheduler configuration or host detail is exposed.
    """
    if not settings.KLLM_ENABLED:
        raise KllmDisabledError(DISABLED_MESSAGE)
    payload, error = await _fetch_json(
        "/admin/api/autoscale/config", timeout=settings.KLLM_STATE_TIMEOUT_S
    )
    if payload is None:
        raise KllmUnavailableError(
            error or "kLLM autoscale configuration is unavailable."
        )
    unverified = {
        "reachable": True,
        "desired_pool": None,
        "autoscale_min_backends": None,
        "size": None,
        "effectively_disabled": None,
        "verified": False,
        "enabled": None,
    }
    settings_map = payload.get("settings")
    if not isinstance(settings_map, dict):
        return unverified
    if "min_backends" not in settings_map or "desired_pool" not in payload:
        return unverified

    def _non_negative_int(value):
        if isinstance(value, bool):
            return None
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        return number if number >= 0 else None

    min_backends = _non_negative_int(settings_map.get("min_backends"))
    desired_pool = _non_negative_int(payload.get("desired_pool"))
    if min_backends is None or desired_pool is None:
        return unverified

    effective_size = max(min_backends, desired_pool)
    return {
        "reachable": True,
        "desired_pool": desired_pool,
        "autoscale_min_backends": min_backends,
        "size": effective_size,
        "effectively_disabled": effective_size == 0,
        "verified": True,
        "enabled": bool(settings_map.get("enabled", True)),
    }


async def set_keep(
    db: AsyncSession, size: int, *, confirm: bool = False
) -> dict[str, Any]:
    """Set kLLM's desired pool and re-read the effective always-on state.

    kLLM also enforces ``autoscale.min_backends``, so changing ``desired_pool``
    alone cannot always disable the always-on default model. The response never
    claims an effective disablement that could not be verified upstream.
    """
    if not await is_enabled(db):
        raise KllmDisabledError(
            DISABLED_MESSAGE
        )
    if size < 0 or size > 10:
        raise KllmConflictError("The always-on pool size must be between 0 and 10.")
    if size > 0:
        _require_confirm(confirm)
    await _post_json("/admin/api/keep", {"size": size})
    invalidate_cache()
    try:
        config = await get_autoscale_config()
    except KllmError:
        return {
            "status": "always_on_update_unverified",
            "size": size,
            "desired_pool_size": size,
            "effective_min_backends": None,
            "effective_size": None,
            "effectively_disabled": None,
            "verified": False,
        }
    verified = bool(config.get("verified"))
    effective_size = config.get("size")
    if not verified or effective_size is None:
        return {
            "status": "always_on_update_unverified",
            "size": size,
            "desired_pool_size": size,
            "effective_min_backends": None,
            "effective_size": None,
            "effectively_disabled": None,
            "verified": False,
        }
    return {
        "status": (
            "always_on_disabled"
            if effective_size == 0
            else "always_on_update_incomplete"
        ),
        "size": size,
        "desired_pool_size": size,
        "effective_min_backends": config.get("autoscale_min_backends"),
        "effective_size": effective_size,
        "effectively_disabled": bool(config.get("effectively_disabled")),
        "verified": True,
    }


def _available_model_row(
    model: KllmModel, *, loads_on_demand: bool, stamp: str
) -> dict[str, Any]:
    return {
        "model_name": model.key,
        "canonical_model_name": model.key,
        "provider": KLLM_SLUG,
        "accessible": True,
        "admin_disabled": False,
        "deprecated": False,
        "preview": False,
        "experimental": False,
        "enterprise_only": False,
        "region_supported": True,
        "context_window": model.context_window,
        "input_cost": 0.0,
        "output_cost": 0.0,
        "supports_streaming": True,
        "supports_function_calling": True,
        "supports_vision": model.vision,
        "supports_reasoning": True,
        "status": model.status,
        "readiness": model.readiness,
        "reason_code": model.reason_code,
        "loads_on_demand": loads_on_demand,
        "validation_timestamp": stamp,
    }


async def build_available_models(
    db: AsyncSession, *, approved_unloaded: set[str] | None = None
) -> list[dict[str, Any]]:
    """Model metadata for the repository config modal.

    Ready models are always offered. An unloaded model is also offered when
    the administrator explicitly approved it for review-demand loading; the
    row is marked ``loads_on_demand`` so the UI never implies it is ready.
    """
    snapshot = await get_snapshot(db)
    if not snapshot.enabled or not snapshot.reachable:
        return []

    approved = approved_unloaded or set()
    stamp = datetime.now(UTC).isoformat()
    rows: list[dict[str, Any]] = []
    for model in snapshot.models:
        loads_on_demand = (
            not model.ready
            and model.key in approved
            and model.status in ("unloaded", "loading")
        )
        if not model.ready and not loads_on_demand:
            continue
        rows.append(
            _available_model_row(
                model, loads_on_demand=loads_on_demand, stamp=stamp
            )
        )
    return rows


async def get_model_options(db: AsyncSession) -> list[dict[str, Any]]:
    """Read-only model options for ordinary users.

    Includes ready models plus administrator-approved unloaded models, each
    with the backend-computed readiness projection. Never exposes controls.
    """
    snapshot = await get_snapshot(db)
    if not snapshot.enabled or not snapshot.reachable:
        return []

    from app.services import kllm_autoload

    policy = await kllm_autoload.get_policy(db)
    approved = (
        set(policy["review_autoload"]["allowed_models"])
        if policy["review_autoload"]["enabled"]
        else set()
    )
    stamp = datetime.now(UTC).isoformat()
    rows: list[dict[str, Any]] = []
    for model in snapshot.models:
        loads_on_demand = (
            not model.ready
            and model.key in approved
            and model.status in ("unloaded", "loading")
        )
        if not model.ready and not loads_on_demand:
            continue
        rows.append(
            _available_model_row(
                model, loads_on_demand=loads_on_demand, stamp=stamp
            )
        )
    return rows
