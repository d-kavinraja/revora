"""Revora-managed hosted Ollama provider (Chat only).

This is a separate provider namespace from kLLM. Enabling or disabling hosted
models never touches the kLLM provider, its readiness projection or the review
pathway. Revora only:

* discovers the installed inventory from Ollama's ``/api/tags`` and the
  **runtime-loaded** set from ``/api/ps``. Installed-but-unloaded models are
  listed so an operator can see them, but only an ``/api/ps``-confirmed model is
  ever ``ready``; a model is never auto-loaded just to list or select it;
* enriches each model with metadata from ``/api/tags`` and ``/api/show``, and
  prefers the loaded runner's own context length reported by ``/api/ps``;
* enforces a configurable global + per-model concurrency cap with a bounded
  queue, releasing every permit on success, error, timeout and cancellation;
* optionally wakes the hosting machine and holds an activity lease so an idle
  pause cannot interrupt an in-flight request. Revora never changes the remote
  Ollama binding or infrastructure.

All configuration comes from validated backend settings. The endpoint URL,
bearer token and wake API key are server-side only and are never returned by
the API or written to logs. No prompts, responses or chat metadata are
persisted here.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlparse

import anyio
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import keep_alive_payload_value, settings
from app.db.session import AsyncSessionLocal
from app.models.platform import PlatformSetting

logger = logging.getLogger(__name__)

HOSTED_PROVIDER_SLUG = "hosted-ollama"
HOSTED_MODEL_PREFIX = "hosted-ollama:"
HOSTED_CATEGORY = "hosted"
COORD_KEY = "hosted_ollama_coordination"

#: User-facing text for "hosted models are off". Free of env paths, variable
#: names and restart steps, matching the kLLM disabled-message contract.
DISABLED_MESSAGE = "Hosted models are currently unavailable."

SELECTION_KEY = "hosted_ollama"
SELECTION_TTL_SECONDS = 5.0

#: Ollama model identifiers are ``name:tag`` (e.g. ``qwen3:1.7b-q4_K_M``). The
#: value travels in a JSON body, never a URL path, but is still validated so a
#: malformed or hostile identifier can never reach the runtime.
_MODEL_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/\-]{0,199}")


# --- errors -----------------------------------------------------------------


class HostedError(Exception):
    """Base error with a safe, client-facing message and stable reason code."""

    code = "hosted_error"
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
        self.reason_code = reason_code or self.code
        super().__init__(message)


class HostedDisabledError(HostedError):
    code = "hosted_disabled"
    status_code = 503


class HostedNotConfiguredError(HostedError):
    code = "hosted_not_configured"
    status_code = 503


class HostedUnavailableError(HostedError):
    code = "hosted_unavailable"
    status_code = 503


class HostedNotFoundError(HostedError):
    code = "hosted_not_found"
    status_code = 404


class HostedBusyError(HostedError):
    code = "hosted_busy"
    status_code = 503


class HostedAuthError(HostedError):
    code = "hosted_auth_error"
    status_code = 502


class HostedRedirectError(HostedError):
    """A hosted response asked us to follow a redirect that leaves the origin."""

    code = "hosted_redirect"
    status_code = 502


# --- DTOs -------------------------------------------------------------------


@dataclass
class HostedModel:
    key: str
    model: str
    installed: bool = True
    loaded: bool = False
    status: str = "unloaded"
    ready: bool = False
    readiness: str = "unloaded"
    reason_code: str = "model_not_loaded"
    context_window: int | None = None
    vision: bool = False
    tags: list[str] = field(default_factory=list)
    resident: bool = False
    digest: str | None = None
    admin_loadable: bool = True
    runtime_unknown: bool = False
    #: ISO timestamp of the discovery pass that produced this row.
    last_verified_at: str | None = None
    #: True when only one of ``/api/tags`` and ``/api/ps`` answered.
    partial: bool = False
    #: Genuine admin-initiated load operation state, when one is tracked.
    load_state: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "provider": HOSTED_PROVIDER_SLUG,
            "category": HOSTED_CATEGORY,
            "display_name": self.model,
            "model": self.model,
            "installed": self.installed,
            "loaded": self.loaded,
            "status": self.status,
            "ready": self.ready,
            "readiness": self.readiness,
            "reason_code": self.reason_code,
            "context_window": self.context_window,
            "vision": self.vision,
            "tags": self.tags,
            "resident": self.resident,
            "digest": self.digest,
            "admin_loadable": self.admin_loadable,
            "runtime_unknown": self.runtime_unknown,
            "last_verified_at": self.last_verified_at,
            "partial": self.partial,
            "load_state": self.load_state,
            "backend_count": 1,
        }


@dataclass
class _RawState:
    fetched_at: float
    reachable: bool
    stale: bool
    error: str | None
    models: list[HostedModel]
    version: str | None = None
    tags_ok: bool = False
    ps_ok: bool = False
    partial: bool = False
    runtime_unknown: bool = False


@dataclass
class HostedSnapshot:
    enabled: bool
    configured: bool
    reachable: bool
    stale: bool
    generated_at: datetime
    age_seconds: float
    error: str | None
    models: list[HostedModel]
    selection_enabled: bool
    wake_enabled: bool
    waking: bool
    version: str | None
    concurrency: dict[str, Any]
    partial: bool = False
    runtime_unknown: bool = False
    installed_count: int = 0
    loaded_count: int = 0
    #: Provider-level, backend-confirmed discovery state. The UI renders banners
    #: from these values instead of inferring a provider state itself.
    state: str = "unknown"
    reason: str = "unknown"
    discovery_ok: bool = False
    last_success_at: str | None = None
    cooldown_until: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "configured": self.configured,
            "reachable": self.reachable,
            "stale": self.stale,
            "generated_at": self.generated_at,
            "age_seconds": self.age_seconds,
            "error": self.error,
            "models": [m.as_dict() for m in self.models],
            "selection_enabled": self.selection_enabled,
            "wake_enabled": self.wake_enabled,
            "waking": self.waking,
            "version": self.version,
            "concurrency": self.concurrency,
            "partial": self.partial,
            "runtime_unknown": self.runtime_unknown,
            "installed_count": sum(1 for m in self.models if m.installed),
            "loaded_count": sum(1 for m in self.models if m.loaded),
            "state": self.state,
            "reason": self.reason,
            "discovery_ok": self.discovery_ok,
            "last_success_at": self.last_success_at,
            "cooldown_until": self.cooldown_until,
        }


def _snapshot_state(
    *,
    enabled: bool,
    configured: bool,
    reachable: bool,
    stale: bool,
    waking: bool,
    partial: bool,
    runtime_unknown: bool,
) -> tuple[str, str]:
    """Derive a provider-level ``(state, reason)`` from confirmed evidence only."""
    if not enabled:
        return "disabled", "hosted_disabled"
    if not configured:
        return "unconfigured", "hosted_not_configured"
    if waking:
        return "waking", "hosted_waking"
    if not reachable:
        return "unreachable", "hosted_unreachable"
    if stale:
        return "stale", "hosted_state_stale"
    if runtime_unknown:
        return "verifying", "runtime_unknown"
    if partial:
        return "partial", "discovery_partial"
    return "ready", "ready"


# --- key helpers ------------------------------------------------------------


def is_hosted_key(key: str | None) -> bool:
    return isinstance(key, str) and key.startswith(HOSTED_MODEL_PREFIX)


def hosted_key(model: str) -> str:
    return f"{HOSTED_MODEL_PREFIX}{model}"


def parse_hosted_key(key: str | None) -> str | None:
    """Return the bare Ollama model name for a hosted key, or ``None``.

    Raises a definitive error for a malformed identifier so a hostile value can
    never reach the runtime. Never substitutes another model.
    """
    if not is_hosted_key(key):
        return None
    name = key[len(HOSTED_MODEL_PREFIX):]
    if not _MODEL_NAME_RE.fullmatch(name):
        raise HostedUnavailableError(
            "Invalid hosted model identifier.", definitive=True,
            reason_code="invalid_model",
        )
    return name


# --- endpoint validation (SSRF) --------------------------------------------


def _validated_base_url() -> str:
    """Validate the operator-configured endpoint and return its origin.

    The URL comes from backend settings (not user input), but is still checked:
    only http/https, no userinfo, no path/query/fragment, and no link-local /
    metadata / reserved addresses. Loopback and private ranges are allowed
    because the hosted runtime is reached over a private transport (e.g. an SSH
    port-forward). Redirects are never followed by the client.
    """
    raw = str(getattr(settings, "REVORA_HOSTED_OLLAMA_BASE_URL", "") or "").strip().rstrip("/")
    if not raw:
        raise HostedNotConfiguredError(
            "Hosted Ollama is not configured with a server URL.",
            reason_code="hosted_not_configured",
        )
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HostedNotConfiguredError(
            "Hosted Ollama is not configured with a valid server URL.",
            reason_code="hosted_not_configured",
        )
    if parsed.username or parsed.password:
        raise HostedNotConfiguredError(
            "Hosted Ollama URL must not embed credentials.",
            reason_code="hosted_not_configured",
        )
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise HostedNotConfiguredError(
            "Hosted Ollama URL must be an origin without a path.",
            reason_code="hosted_not_configured",
        )
    host = (parsed.hostname or "").lower()
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if (
            ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise HostedNotConfiguredError(
                "Hosted Ollama URL points at a disallowed address.",
                reason_code="hosted_not_configured",
            )
    return raw


def is_configured() -> bool:
    try:
        _validated_base_url()
        return True
    except HostedError:
        return False


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    token = str(getattr(settings, "REVORA_HOSTED_OLLAMA_TOKEN", "") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _with_token(url: str) -> str:
    token = str(getattr(settings, "REVORA_HOSTED_OLLAMA_URL_TOKEN", "") or "").strip()
    if not token:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}_token={quote(token, safe='')}"


def endpoint_url(path: str) -> str:
    """Build a validated hosted URL, appending the private-port token if any.

    The gateway token is a query parameter (``_token``), never a header and
    never part of the configured origin. It is server-side only.
    """
    return _with_token(f"{_validated_base_url()}{path}")


_REDIRECT_STATUSES = (301, 302, 303, 307, 308)


def same_origin_redirect_target(response: httpx.Response) -> str | None:
    """Resolve a gateway login redirect to a safe same-origin target.

    Returns ``None`` when the response is not a redirect (so the caller keeps the
    original response). Raises :class:`HostedRedirectError` for a cross-origin or
    unsupported redirect, which preserves the SSRF protection that forbids
    leaving the operator-configured origin. Only the origin of the configured
    base URL is trusted; no configuration value is ever included in the error.
    """
    if response.status_code not in _REDIRECT_STATUSES:
        return None
    location = response.headers.get("location")
    if not location:
        return None
    base = _validated_base_url()
    parsed = urlparse(location)
    if parsed.scheme or parsed.netloc:
        if parsed.scheme not in ("http", "https") or parsed.netloc != urlparse(base).netloc:
            raise HostedRedirectError(
                "Hosted Ollama returned a disallowed redirect.",
                reason_code="hosted_redirect",
            )
        return location
    relative = location if location.startswith("/") else f"/{location}"
    return f"{base}{relative}"


async def _request_with_gateway_login(
    method: str,
    path: str,
    *,
    timeout: float | None,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[httpx.Response | None, str | None]:
    """Issue a JSON request, following ONLY a same-origin gateway login redirect.

    Private port links answer the first tokenized request with 303 + Set-Cookie
    and a relative Location. Redirects to any other origin are rejected so SSRF
    protection is preserved. The shared client keeps the cookie for later calls.
    """
    response = await _get_client().request(
        method, endpoint_url(path), json=payload, headers=headers, timeout=timeout
    )
    try:
        target = same_origin_redirect_target(response)
    except HostedError as exc:
        return None, exc.message
    if target is None:
        return response, None
    # The gateway sets a cookie on the 303; re-sending the token would trigger
    # another redirect, so the follow-up relies on the shared client's cookie.
    response = await _get_client().request(
        method, target, json=payload, headers=headers, timeout=timeout
    )
    return response, None


# --- shared HTTP client -----------------------------------------------------

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=settings.REVORA_HOSTED_OLLAMA_CONNECT_TIMEOUT_S,
                read=settings.REVORA_HOSTED_OLLAMA_READ_TIMEOUT_S,
                write=120.0,
                pool=10.0,
            ),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            follow_redirects=False,
        )
    return _client


async def aclose() -> None:
    """Close the shared client. Called from the application lifespan shutdown."""
    global _client
    client, _client = _client, None
    if client is not None and not client.is_closed:
        await client.aclose()
    await _close_redis()


def _safe_error(exc: Exception | None, fallback: str) -> str:
    if exc is None:
        return fallback
    if isinstance(exc, httpx.TimeoutException):
        return "Hosted Ollama request timed out."
    if isinstance(exc, httpx.HTTPError):
        return "Hosted Ollama is unreachable."
    return fallback


async def _fetch_json(path: str, *, timeout: float) -> tuple[dict[str, Any] | None, str | None]:
    try:
        endpoint_url(path)
    except HostedError as exc:
        return None, exc.message
    try:
        response, redirect_error = await _request_with_gateway_login(
            "GET", path, timeout=timeout, headers=_headers()
        )
    except Exception as exc:
        logger.warning("hosted GET %s failed: %s", path, type(exc).__name__)
        return None, _safe_error(exc, "Hosted Ollama is unreachable.")
    if response is None:
        return None, redirect_error
    if response.status_code in (401, 403):
        return None, "Hosted Ollama rejected the server credentials."
    if response.status_code >= 500:
        return None, "Hosted Ollama is temporarily unavailable."
    if response.status_code != 200:
        return None, f"Hosted Ollama returned HTTP {response.status_code}."
    try:
        data = response.json()
    except ValueError:
        return None, "Hosted Ollama returned an invalid response."
    if not isinstance(data, dict):
        return None, "Hosted Ollama returned an invalid response."
    return data, None


async def _post_json(path: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any] | None:
    headers = _headers()
    headers["Content-Type"] = "application/json"
    try:
        response, _redirect_error = await _request_with_gateway_login(
            "POST", path, timeout=timeout, payload=payload, headers=headers
        )
    except Exception as exc:
        logger.warning("hosted POST %s failed: %s", path, type(exc).__name__)
        return None
    if response is None or response.status_code != 200:
        return None
    try:
        data = response.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


# --- admin selection toggle (backend-enforced) -----------------------------

_selection_cache: dict[str, Any] | None = None
_selection_cache_at: float = 0.0


def _selection_cached() -> dict[str, Any] | None:
    if _selection_cache is None:
        return None
    if (time.monotonic() - _selection_cache_at) >= SELECTION_TTL_SECONDS:
        return None
    return _selection_cache


async def get_selection(db: AsyncSession | None = None) -> bool:
    """Whether an administrator allows hosted selection. Fail-open ``True``.

    A missing row or an unreachable DB means "enabled", so the environment flag
    alone controls the provider until an administrator explicitly disables it.
    """
    cached = _selection_cached()
    if cached is not None:
        return bool(cached.get("enabled", True))
    enabled = True
    try:
        if db is not None:
            result = await db.execute(
                select(PlatformSetting).where(PlatformSetting.key == SELECTION_KEY)
            )
            row = result.scalars().first()
            if row is not None and isinstance(row.value, dict):
                enabled = bool(row.value.get("enabled", True))
    except Exception:
        logger.warning("Hosted selection read failed; assuming enabled", exc_info=True)
        if db is not None:
            try:
                await db.rollback()
            except Exception:
                pass
        enabled = True
    value = {"enabled": enabled}
    global _selection_cache, _selection_cache_at
    _selection_cache = value
    _selection_cache_at = time.monotonic()
    return enabled


async def set_selection(
    db: AsyncSession, *, enabled: bool, admin_id: Any = None
) -> dict[str, Any]:
    """Upsert the selection row (write-through cache). Caller commits/audits."""
    global _selection_cache, _selection_cache_at
    await db.flush()
    result = await db.execute(
        select(PlatformSetting).where(PlatformSetting.key == SELECTION_KEY)
    )
    row = result.scalars().first()
    row_version = int(row.version or 1) if row is not None else 0
    new_value = {
        "enabled": bool(enabled),
        "changed_at": datetime.now(UTC).isoformat(),
        "changed_by": str(admin_id) if admin_id is not None else "system",
        "version": row_version + 1,
    }
    if row is None:
        row = PlatformSetting(
            key=SELECTION_KEY, value=new_value, updated_by=admin_id, version=1
        )
        db.add(row)
    else:
        row.value = new_value
        row.updated_by = admin_id
        row.version = row_version + 1
        db.add(row)
    _selection_cache = {"enabled": bool(enabled)}
    _selection_cache_at = time.monotonic()
    return dict(new_value)


async def is_enabled(db: AsyncSession | None = None) -> bool:
    """Both the runtime flag and the admin selection toggle must agree."""
    if not settings.REVORA_HOSTED_OLLAMA_ENABLED:
        return False
    return await get_selection(db)


# --- discovery --------------------------------------------------------------

_raw_cache: _RawState | None = None
# Last confirmed successful discovery (ISO-8601, UTC) and any wake cooldown the
# wake API reported. Both are evidence, never inferred.
_last_success_at: str | None = None
_cooldown_until: float | None = None

# In-flight admin load operations (evidence-based "loading" state). In-process
# only; cross-worker safety is the load lease, not this dict.
_load_ops: dict[str, dict[str, Any]] = {}


def invalidate_cache() -> None:
    global _raw_cache
    _raw_cache = None


def _context_and_capabilities(show: dict[str, Any] | None) -> tuple[int | None, bool]:
    if not isinstance(show, dict):
        return None, False
    context_window: int | None = None
    info = show.get("model_info")
    if isinstance(info, dict):
        for key, value in info.items():
            if isinstance(key, str) and key.endswith(".context_length"):
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    context_window = int(value)
                    break
    capabilities = show.get("capabilities")
    vision = False
    if isinstance(capabilities, list):
        vision = any(isinstance(c, str) and c.lower() == "vision" for c in capabilities)
    return context_window, vision


def _runtime_context(entry: dict[str, Any]) -> int | None:
    """Read the context length a loaded runner reports in ``/api/ps``.

    Ollama reports it either as a top-level ``context_length`` or inside the
    entry's ``details``/``model_info`` block depending on version. Only a real
    positive number is accepted; nothing is inferred.
    """
    candidates: list[Any] = [entry.get("context_length")]
    details = entry.get("details")
    if isinstance(details, dict):
        candidates.append(details.get("context_length"))
    info = entry.get("model_info")
    if isinstance(info, dict):
        for key, value in info.items():
            if isinstance(key, str) and key.endswith(".context_length"):
                candidates.append(value)
                break
    for value in candidates:
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return int(value)
    return None


def _tags_for(details: dict[str, Any] | None) -> list[str]:
    tags: list[str] = []
    if isinstance(details, dict):
        for key in ("family", "parameter_size", "quantization_level"):
            value = details.get(key)
            if isinstance(value, str) and value:
                tags.append(value)
    return tags


async def _read_raw_state(force: bool = False) -> _RawState:
    global _raw_cache, _last_success_at
    now = time.monotonic()
    ttl = settings.REVORA_HOSTED_OLLAMA_CACHE_TTL_S
    if not force and _raw_cache is not None and now - _raw_cache.fetched_at < ttl:
        return _raw_cache

    timeout = settings.REVORA_HOSTED_OLLAMA_DISCOVERY_TIMEOUT_S
    ps, ps_err = await _fetch_json("/api/ps", timeout=timeout)
    tags, tags_err = await _fetch_json("/api/tags", timeout=timeout)
    ps_ok = ps is not None
    tags_ok = tags is not None
    partial = tags_ok != ps_ok
    verified_at = datetime.now(UTC).isoformat()

    # Transport-level failure: neither source answered. Serve stale cache if any;
    # never fabricate a loaded=False state from a failed runtime discovery.
    if not ps_ok and not tags_ok:
        if _raw_cache is not None and _raw_cache.reachable:
            previous = _raw_cache
            return _RawState(
                fetched_at=previous.fetched_at,
                reachable=True,
                stale=True,
                error=ps_err or tags_err,
                models=previous.models,
                version=previous.version,
                tags_ok=previous.tags_ok,
                ps_ok=previous.ps_ok,
                partial=previous.partial,
                runtime_unknown=previous.runtime_unknown,
            )
        return _RawState(now, False, False, ps_err or tags_err, [], None,
                        tags_ok=False, ps_ok=False, partial=False, runtime_unknown=True)

    # Installed inventory from /api/tags (never from /api/ps).
    installed: dict[str, dict[str, Any]] = {}
    if tags_ok:
        raw_models = tags.get("models")
        if isinstance(raw_models, list):
            for item in raw_models:
                if not isinstance(item, dict):
                    continue
                name = item.get("name") or item.get("model")
                if isinstance(name, str) and _MODEL_NAME_RE.fullmatch(name):
                    installed[name] = item

    # Runtime-loaded set from /api/ps. Only a successful /api/ps may assert
    # loaded=True; a failed /api/ps leaves loaded as unknown, never False. The
    # runner also reports the context length it was actually started with, which
    # is authoritative over catalog metadata for a loaded model.
    loaded_names: set[str] = set()
    loaded_context: dict[str, int] = {}
    if ps_ok:
        raw_ps = ps.get("models")
        if isinstance(raw_ps, list):
            for entry in raw_ps:
                if not isinstance(entry, dict):
                    continue
                name = entry.get("name") or entry.get("model")
                if isinstance(name, str) and _MODEL_NAME_RE.fullmatch(name):
                    loaded_names.add(name)
                    context = _runtime_context(entry)
                    if context is not None:
                        loaded_context[name] = context

    runtime_unknown = not ps_ok

    # Enrichment cache keyed by (name, digest) to avoid repeated /api/show calls.
    show_cache: dict[tuple[str, str | None], dict[str, Any] | None] = {}
    if _raw_cache is not None:
        for m in _raw_cache.models:
            # We cannot recover the show payload, but we keep the digest for
            # cache-key stability; show is re-fetched only for new digests.
            pass

    # Resolve which installed names need a fresh /api/show call. Only fetch for
    # names not already in the in-process cache OR whose digest changed.
    names_needing_show: list[str] = []
    for name, item in installed.items():
        digest = item.get("digest") if isinstance(item.get("digest"), str) else None
        # Always fetch capabilities if we don't have a cached result. The cache
        # is the _raw_cache models' context/vision, but capabilities require show.
        names_needing_show.append(name)

    # Bound the number of concurrent show calls to the installed set (small).
    shows = await asyncio.gather(
        *(_post_json("/api/show", {"model": n}, timeout=timeout) for n in names_needing_show)
    )
    show_map = dict(zip(names_needing_show, shows))

    # Tracked loading operations (admin-initiated) — evidence-based only.
    loading_names = set(_load_ops.keys())

    models: list[HostedModel] = []
    # Installed inventory first.
    for name, item in installed.items():
        digest = item.get("digest") if isinstance(item.get("digest"), str) else None
        details = item.get("details") if isinstance(item.get("details"), dict) else None
        context_window = None
        if isinstance(details, dict):
            value = details.get("context_length")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                context_window = int(value)
        vision = False
        show = show_map.get(name)
        show_ctx, show_vision = _context_and_capabilities(show)
        if context_window is None:
            context_window = show_ctx
        if show_vision:
            vision = True
        loaded = name in loaded_names if ps_ok else False
        # If runtime is unknown, we cannot assert loaded; mark loaded=False but
        # readiness becomes "unknown", never a verified "ready".
        if runtime_unknown:
            loaded = False
        if loaded and name in loaded_context:
            # The loaded runner's own context length wins over catalog metadata.
            context_window = loaded_context[name]

        # Genuine, admin-initiated load operation state (never inferred).
        op = _load_ops.get(name) if name in loading_names else None
        load_state: str | None = None
        if isinstance(op, dict):
            raw_state = op.get("state")
            load_state = str(raw_state) if raw_state else None
        loading = load_state in ("queued", "loading") and not loaded
        verifying = load_state == "verifying" and not loaded
        if loading:
            readiness = "loading"
            reason_code = "model_loading"
            status = "loading"
        elif verifying:
            readiness = "verifying"
            reason_code = "model_verifying"
            status = "verifying"
        elif runtime_unknown:
            readiness = "unknown"
            reason_code = "runtime_unknown"
            status = "unknown"
        elif loaded:
            readiness = "ready"
            reason_code = "ready"
            status = "loaded"
        else:
            readiness = "unloaded"
            reason_code = "model_not_loaded"
            status = "installed"
        tags_list = _tags_for(details)
        if isinstance(show, dict):
            # Merge family from show only if missing.
            pass
        models.append(
            HostedModel(
                key=hosted_key(name),
                model=name,
                installed=True,
                loaded=loaded,
                status=status,
                ready=loaded and not runtime_unknown,
                readiness=readiness,
                reason_code=reason_code,
                context_window=context_window,
                vision=vision,
                tags=tags_list,
                resident=loaded,
                digest=digest,
                admin_loadable=(not loaded),
                runtime_unknown=runtime_unknown,
                last_verified_at=verified_at,
                partial=partial,
                load_state=load_state,
            )
        )

    # If installed inventory is unknown but runtime is known, show loaded models
    # as installed-unknown (best-effort, clearly marked).
    if not tags_ok and ps_ok:
        for name in sorted(loaded_names):
            if name in installed:
                continue
            if not _MODEL_NAME_RE.fullmatch(name):
                continue
            show = show_map.get(name) if name in show_map else None
            # fetch show for these too (bounded)
            if show is None:
                show = await _post_json("/api/show", {"model": name}, timeout=timeout)
            ctx, vis = _context_and_capabilities(show)
            if name in loaded_context:
                ctx = loaded_context[name]
            models.append(
                HostedModel(
                    key=hosted_key(name),
                    model=name,
                    installed=False,
                    loaded=True,
                    status="loaded",
                    ready=True,
                    readiness="ready",
                    reason_code="ready",
                    context_window=ctx,
                    vision=vis,
                    tags=[],
                    resident=True,
                    digest=None,
                    admin_loadable=False,
                    runtime_unknown=False,
                    last_verified_at=verified_at,
                    partial=partial,
                    load_state=None,
                )
            )

    models.sort(key=lambda m: m.model)

    # Reconcile tracked load operations against fresh discovery. Only clear an
    # op when discovery confirms the outcome; never fabricate "loaded".
    for name in list(_load_ops):
        op = _load_ops.get(name)
        if not isinstance(op, dict):
            _load_ops.pop(name, None)
            continue
        is_loaded = any(m.model == name and m.loaded for m in models)
        if is_loaded:
            _load_ops.pop(name, None)
            continue
        if time.monotonic() - float(op.get("started", now)) > settings.REVORA_HOSTED_READY_TIMEOUT_S:
            _load_ops.pop(name, None)

    # Version probe.
    version_data, _ = await _fetch_json("/api/version", timeout=timeout)
    version = None
    if isinstance(version_data, dict) and isinstance(version_data.get("version"), str):
        version = version_data["version"]

    partial = tags_ok != ps_ok
    # Reachable = at least one of the two discovery endpoints answered.
    reachable = bool(tags_ok or ps_ok)
    error = None
    if not reachable:
        error = ps_err or tags_err

    state = _RawState(
        now, reachable, False, error, models, version,
        tags_ok=tags_ok, ps_ok=ps_ok, partial=partial, runtime_unknown=runtime_unknown,
    )
    if reachable:
        _last_success_at = datetime.now(UTC).isoformat()
    # Stale serve already handled above; mark stale only if we served previous.
    _raw_cache = state
    return state


def _cooldown_until_iso() -> str | None:
    """Return an active wake cooldown as ISO-8601, or ``None`` when none is set."""
    global _cooldown_until
    if _cooldown_until is None:
        return None
    if _cooldown_until <= time.time():
        _cooldown_until = None
        return None
    return datetime.fromtimestamp(_cooldown_until, UTC).isoformat()


async def get_snapshot(db: AsyncSession | None = None, *, force: bool = False) -> HostedSnapshot:
    env_enabled = bool(settings.REVORA_HOSTED_OLLAMA_ENABLED)
    selection = await get_selection(db) if env_enabled else True
    enabled = env_enabled and selection
    configured = is_configured()
    generated_at = datetime.now(UTC)

    if not enabled:
        state, reason = _snapshot_state(
            enabled=False,
            configured=configured,
            reachable=False,
            stale=False,
            waking=_waking,
            partial=False,
            runtime_unknown=False,
        )
        return HostedSnapshot(
            enabled=False,
            configured=configured,
            reachable=False,
            stale=False,
            generated_at=generated_at,
            age_seconds=0.0,
            error=None,
            models=[],
            selection_enabled=selection,
            wake_enabled=bool(settings.REVORA_HOSTED_WAKE_ENABLED),
            waking=_waking,
            version=None,
            concurrency=concurrency_status(),
            partial=False,
            runtime_unknown=False,
            installed_count=0,
            loaded_count=0,
            state=state,
            reason=reason,
            discovery_ok=False,
            last_success_at=_last_success_at,
            cooldown_until=_cooldown_until_iso(),
        )

    raw = await _read_raw_state(force=force)
    age = max(0.0, time.monotonic() - raw.fetched_at)
    state, reason = _snapshot_state(
        enabled=True,
        configured=configured,
        reachable=raw.reachable,
        stale=raw.stale,
        waking=_waking,
        partial=raw.partial,
        runtime_unknown=raw.runtime_unknown,
    )
    return HostedSnapshot(
        enabled=True,
        configured=configured,
        reachable=raw.reachable,
        stale=raw.stale,
        generated_at=generated_at,
        age_seconds=age,
        error=raw.error,
        models=raw.models if raw.reachable and not raw.stale else [],
        selection_enabled=selection,
        wake_enabled=bool(settings.REVORA_HOSTED_WAKE_ENABLED),
        waking=_waking,
        version=raw.version,
        concurrency=concurrency_status(),
        partial=raw.partial,
        runtime_unknown=raw.runtime_unknown,
        installed_count=sum(1 for m in raw.models if m.installed),
        loaded_count=sum(1 for m in raw.models if m.loaded),
        state=state,
        reason=reason,
        discovery_ok=bool(raw.reachable and not raw.stale),
        last_success_at=_last_success_at,
        cooldown_until=_cooldown_until_iso(),
    )


async def ensure_model_ready(db: AsyncSession | None, key: str) -> HostedModel:
    """Execution-time validation for a hosted model. Never substitutes or loads.

    Only a runtime-loaded model passes. If the endpoint is unreachable and wake
    is enabled, Revora wakes the machine and re-discovers; it never auto-loads a
    model just to satisfy a selection.
    """
    if not settings.REVORA_HOSTED_OLLAMA_ENABLED:
        raise HostedDisabledError(DISABLED_MESSAGE)
    if not await get_selection(db):
        raise HostedDisabledError(
            "Hosted models are currently disabled by an administrator."
        )
    name = parse_hosted_key(key)
    if name is None:
        raise HostedUnavailableError(
            "A hosted model must be selected.", definitive=True,
            reason_code="invalid_model",
        )
    if not is_configured():
        raise HostedNotConfiguredError(
            "Hosted Ollama is not configured.", definitive=True
        )

    snapshot = await get_snapshot(db, force=True)
    if not snapshot.reachable and snapshot.wake_enabled:
        # Don't wake the machine for a model we already know is not loaded.
        cached_loaded = None
        if _raw_cache is not None:
            for m in _raw_cache.models:
                if m.model == name:
                    cached_loaded = m.loaded
                    break
        if cached_loaded is False:
            raise HostedUnavailableError(
                f"Model '{name}' is not loaded on the hosted runtime.",
                definitive=True,
                reason_code="model_not_loaded",
            )
        await wake_and_wait_ready()
        snapshot = await get_snapshot(db, force=True)
    if not snapshot.reachable:
        raise HostedUnavailableError(
            snapshot.error or "Hosted Ollama is unreachable. The model cannot be verified."
        )
    if snapshot.stale:
        raise HostedUnavailableError(
            "Hosted model state is stale; the model cannot be verified right now."
        )
    match = next((m for m in snapshot.models if m.key == key), None)
    if match is None:
        raise HostedNotFoundError(
            f"Model '{name}' is not available on the hosted runtime.",
            definitive=True,
            reason_code="model_not_found",
        )
    if match.runtime_unknown:
        raise HostedUnavailableError(
            f"Runtime state for '{name}' is unknown; cannot verify it is loaded.",
            definitive=True,
            reason_code="runtime_unknown",
        )
    if not match.loaded:
        raise HostedUnavailableError(
            f"Model '{name}' is not loaded on the hosted runtime.",
            definitive=True,
            reason_code="model_not_loaded",
        )
    return match


# --- concurrency gate -------------------------------------------------------

_global_sem: asyncio.Semaphore | None = None
_model_sems: dict[str, asyncio.Semaphore] = {}
_inflight_global = 0
_inflight_by_model: dict[str, int] = {}
_queued = 0
_counter_lock = asyncio.Lock()

_gate_mode: str | None = None
_redis_client: Any = None
_redis_state = "unknown"  # unknown | ok | down

_REDIS_ACQUIRE_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local expires = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local token = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
local count = redis.call('ZCARD', key)
if count < limit then
  redis.call('ZADD', key, expires, token)
  return 1
end
return 0
"""


def _global_semaphore() -> asyncio.Semaphore:
    global _global_sem
    if _global_sem is None:
        _global_sem = asyncio.Semaphore(settings.REVORA_HOSTED_OLLAMA_MAX_CONCURRENT_REQUESTS)
    return _global_sem


def _model_semaphore(model: str) -> asyncio.Semaphore:
    sem = _model_sems.get(model)
    if sem is None:
        sem = asyncio.Semaphore(settings.REVORA_HOSTED_OLLAMA_MAX_CONCURRENT_REQUESTS_PER_MODEL)
        _model_sems[model] = sem
    return sem


async def _get_redis() -> Any:
    global _redis_client, _redis_state
    if _redis_state == "down":
        return None
    if _redis_client is not None:
        return _redis_client
    url = getattr(settings, "REDIS_URL", None)
    if not url:
        _redis_state = "down"
        return None
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(
            url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2
        )
        await client.ping()
        _redis_client = client
        _redis_state = "ok"
        return client
    except Exception:
        logger.info("Hosted concurrency: Redis unavailable, using in-process gate")
        _redis_state = "down"
        _redis_client = None
        return None


async def _close_redis() -> None:
    global _redis_client, _redis_state
    client, _redis_client = _redis_client, None
    _redis_state = "unknown"
    if client is not None:
        try:
            await client.aclose()
        except Exception:
            pass


async def _resolve_gate_mode() -> str:
    global _gate_mode
    if _gate_mode is not None:
        return _gate_mode
    if getattr(settings, "REDIS_URL", None):
        client = await _get_redis()
        if client is not None:
            _gate_mode = "redis"
            return _gate_mode
    _gate_mode = "local"
    return _gate_mode


def _redis_keys(model: str) -> tuple[str, str]:
    digest = hashlib.sha256(model.encode("utf-8")).hexdigest()[:32]
    return (
        "revora:hosted:conc:global",
        f"revora:hosted:conc:model:{digest}",
    )


async def _local_acquire_pair(model: str, deadline: float) -> bool:
    global_sem = _global_semaphore()
    model_sem = _model_semaphore(model)
    global_taken = False
    model_taken = False
    try:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            await asyncio.wait_for(global_sem.acquire(), timeout=remaining)
        except TimeoutError:
            return False
        global_taken = True
        remaining = max(0.0, deadline - time.monotonic())
        try:
            await asyncio.wait_for(model_sem.acquire(), timeout=remaining)
        except TimeoutError:
            return False
        model_taken = True
        return True
    finally:
        # A partial pair must never leak: cancellation (which is a BaseException,
        # not a TimeoutError) lands here too. Both releases are synchronous, so
        # nothing can interrupt them and no shield is needed.
        if not (global_taken and model_taken):
            if model_taken:
                model_sem.release()
            if global_taken:
                global_sem.release()


def _local_release_pair(model: str) -> None:
    _model_semaphore(model).release()
    _global_semaphore().release()


async def _redis_acquire_pair(model: str, token: str, deadline: float) -> tuple[bool, bool]:
    """Acquire via Redis. Returns ``(acquired, used_local_fallback)``.

    If Redis is unavailable the permit is taken from the in-process gate and
    ``used_local_fallback`` is True so the caller releases the same backend.
    """
    client = await _get_redis()
    if client is None:
        return await _local_acquire_pair(model, deadline), True
    gkey, mkey = _redis_keys(model)
    ttl = (
        settings.REVORA_HOSTED_OLLAMA_READ_TIMEOUT_S
        + settings.REVORA_HOSTED_OLLAMA_QUEUE_TIMEOUT_S
        + 60.0
    )
    global_limit = settings.REVORA_HOSTED_OLLAMA_MAX_CONCURRENT_REQUESTS
    model_limit = settings.REVORA_HOSTED_OLLAMA_MAX_CONCURRENT_REQUESTS_PER_MODEL
    while True:
        now = time.time()
        expires = now + ttl
        got_global = False
        try:
            got_global = int(await client.eval(
                _REDIS_ACQUIRE_LUA, 1, gkey, now, expires, global_limit, token
            )) == 1
            if got_global:
                got_model = int(await client.eval(
                    _REDIS_ACQUIRE_LUA, 1, mkey, now, expires, model_limit, token
                )) == 1
                if got_model:
                    return True, False
                await _redis_drop(client, gkey, token)
        except asyncio.CancelledError:
            # The global slot may already be taken; give it back while the
            # cancellation is shielded, then let the cancellation continue.
            with anyio.CancelScope(shield=True):
                if got_global:
                    await _redis_drop(client, gkey, token)
                    await _redis_drop(client, mkey, token)
            raise
        except Exception:
            if got_global:
                with anyio.CancelScope(shield=True):
                    await _redis_drop(client, gkey, token)
            logger.warning("Hosted Redis permit failed; falling back to in-process gate")
            return await _local_acquire_pair(model, deadline), True
        if time.monotonic() >= deadline:
            return False, False
        await asyncio.sleep(0.05)


async def _redis_drop(client: Any, key: str, token: str) -> None:
    """Remove a membership; a Redis failure must never mask cancellation."""
    try:
        await client.zrem(key, token)
    except Exception:
        logger.warning("Hosted Redis permit cleanup failed for %s", key)


async def _redis_release_pair(model: str, token: str) -> None:
    client = await _get_redis()
    if client is None:
        return
    gkey, mkey = _redis_keys(model)
    try:
        await client.zrem(gkey, token)
        await client.zrem(mkey, token)
    except Exception:
        logger.warning("Hosted Redis permit release failed")


async def _counters_acquire(model: str) -> None:
    global _inflight_global
    async with _counter_lock:
        _inflight_global += 1
        _inflight_by_model[model] = _inflight_by_model.get(model, 0) + 1


async def _counters_release(model: str) -> None:
    global _inflight_global
    async with _counter_lock:
        _inflight_global = max(0, _inflight_global - 1)
        count = _inflight_by_model.get(model, 0) - 1
        if count <= 0:
            _inflight_by_model.pop(model, None)
        else:
            _inflight_by_model[model] = count


async def _queued_inc() -> None:
    global _queued
    async with _counter_lock:
        _queued += 1


async def _queued_dec() -> None:
    global _queued
    async with _counter_lock:
        _queued = max(0, _queued - 1)


@asynccontextmanager
async def permit(model: str):
    """Hold a global + per-model concurrency permit for one hosted request.

    Waits up to ``QUEUE_TIMEOUT_S`` for capacity, then raises ``HostedBusyError``.
    The permit is released on every exit path, including cancellation.
    """
    mode = await _resolve_gate_mode()
    token = uuid.uuid4().hex
    deadline = time.monotonic() + settings.REVORA_HOSTED_OLLAMA_QUEUE_TIMEOUT_S
    await _queued_inc()
    used_local = mode != "redis"
    try:
        if mode == "redis":
            acquired, used_local = await _redis_acquire_pair(model, token, deadline)
        else:
            acquired = await _local_acquire_pair(model, deadline)
    finally:
        await _queued_dec()
    if not acquired:
        raise HostedBusyError(
            "Hosted models are at capacity. Please try again in a moment.",
            reason_code="hosted_busy",
        )
    counters_held = False
    try:
        await _counters_acquire(model)
        counters_held = True
        yield
    finally:
        # Shielded: a cancellation delivered to the request must not stop the
        # release, or the slot would stay taken for the life of the process.
        with anyio.CancelScope(shield=True):
            try:
                if counters_held:
                    await _counters_release(model)
            finally:
                # Release the same backend that granted the permit (a Redis
                # outage can fall back to the in-process gate mid-acquire).
                if used_local:
                    _local_release_pair(model)
                else:
                    await _redis_release_pair(model, token)


def concurrency_status() -> dict[str, Any]:
    return {
        "max_concurrent_requests": settings.REVORA_HOSTED_OLLAMA_MAX_CONCURRENT_REQUESTS,
        "max_concurrent_requests_per_model": settings.REVORA_HOSTED_OLLAMA_MAX_CONCURRENT_REQUESTS_PER_MODEL,
        "queue_timeout_s": settings.REVORA_HOSTED_OLLAMA_QUEUE_TIMEOUT_S,
        "inflight": _inflight_global,
        "queued": _queued,
        "inflight_by_model": dict(_inflight_by_model),
        "distributed": _gate_mode == "redis",
    }


def reset_runtime_state() -> None:
    """Test-only helper to clear in-process gate, cache and selection state."""
    global _global_sem, _raw_cache, _gate_mode, _selection_cache, _selection_cache_at
    global _inflight_global, _queued
    global _last_success_at, _cooldown_until
    _global_sem = None
    _model_sems.clear()
    _inflight_global = 0
    _inflight_by_model.clear()
    _queued = 0
    _raw_cache = None
    _gate_mode = None
    _selection_cache = None
    _selection_cache_at = 0.0
    _last_success_at = None
    _cooldown_until = None




async def redis_client() -> Any:
    """Return the shared Redis client when available, else ``None``.

    Used by the session monitor for cross-worker coordination; fails open to
    the DB-backed fallback when Redis is not configured or unreachable.
    """
    return await _get_redis()


async def claim_lease(kind: str, key: str, ttl: float) -> tuple[bool, str, str]:
    """Acquire a short-lived cross-worker lease.

    Returns ``(acquired, owner, mode)``. Redis when available, DB fallback with
    optimistic versioning. Owner-checked release via :func:`release_lease`.
    """
    owner = uuid.uuid4().hex
    client = await _get_redis()
    if client is not None:
        redis_key = f"revora:hosted:{kind}:{key}"
        try:
            got = await client.set(redis_key, owner, nx=True, ex=max(1, int(ttl)))
            if got:
                return True, owner, "redis"
            return False, owner, "redis"
        except Exception:
            logger.warning("Hosted lease Redis claim failed; using DB fallback")
    # DB fallback: reuse the shared coordination row with a namespaced key.
    db_key = f"{kind}:{key}"
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PlatformSetting).where(PlatformSetting.key == COORD_KEY)
        )
        row = result.scalars().first()
        value = dict(row.value) if row is not None and isinstance(row.value, dict) else {}
        now = time.time()
        until = float(value.get(f"{db_key}_until", 0) or 0)
        holder = value.get(f"{db_key}_owner")
        if until > now and holder and holder != owner:
            return False, owner, "db"
        new = dict(value)
        new[f"{db_key}_until"] = now + ttl
        new[f"{db_key}_owner"] = owner
        if row is None:
            db.add(PlatformSetting(key=COORD_KEY, value=new, version=1))
            await db.commit()
            return True, owner, "db"
        res = await db.execute(
            update(PlatformSetting)
            .where(PlatformSetting.key == COORD_KEY, PlatformSetting.version == row.version)
            .values(value=new, version=row.version + 1)
        )
        await db.commit()
        return bool(res.rowcount == 1), owner, "db"


async def release_lease(kind: str, key: str, owner: str, mode: str) -> None:
    """Release a lease only if the caller is still the owner."""
    if mode == "redis":
        client = await _get_redis()
        if client is not None:
            redis_key = f"revora:hosted:{kind}:{key}"
            try:
                await client.eval(
                    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
                    1, redis_key, owner,
                )
                return
            except Exception:
                logger.warning("Hosted lease Redis release failed; using DB fallback")
    db_key = f"{kind}:{key}"
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PlatformSetting).where(PlatformSetting.key == COORD_KEY)
        )
        row = result.scalars().first()
        if row is None or not isinstance(row.value, dict):
            return
        value = dict(row.value)
        if value.get(f"{db_key}_owner") != owner:
            return
        value[f"{db_key}_until"] = 0
        value[f"{db_key}_owner"] = None
        try:
            await db.execute(
                update(PlatformSetting)
                .where(PlatformSetting.key == COORD_KEY, PlatformSetting.version == row.version)
                .values(value=value, version=row.version + 1)
            )
            await db.commit()
        except Exception:
            await db.rollback()


# --- load operation tracking (in-process, evidence-based) ------------------


async def load_model(db: AsyncSession | None, model: str) -> dict[str, Any]:
    """Explicit, admin-initiated load of an installed hosted model.

    Never triggered by chat, catalog refresh, heartbeat or monitoring. Returns a
    structured result; HTTP success is never treated as proof of loading.
    """
    name = parse_hosted_key(model)
    if name is None:
        raise HostedUnavailableError(
            "A hosted model must be selected.", definitive=True,
            reason_code="invalid_model",
        )

    # Fresh discovery: the model must be installed and not already loaded.
    snapshot = await get_snapshot(db, force=True)
    if not snapshot.reachable:
        if snapshot.wake_enabled:
            await wake_and_wait_ready()
            snapshot = await get_snapshot(db, force=True)
        if not snapshot.reachable:
            raise HostedUnavailableError(
                snapshot.error or "Hosted Ollama is unreachable."
            )
    match = next((m for m in snapshot.models if m.key == model), None)
    if match is None:
        raise HostedNotFoundError(
            f"Model '{name}' is not installed on the hosted runtime.",
            definitive=True,
            reason_code="model_not_found",
        )
    if match.loaded:
        _load_ops.pop(name, None)
        return {"status": "already_loaded", "model": name, "verified": True}

    # Single global slot: non-blocking lease across models AND workers.
    acquired, owner, mode = await claim_lease(
        "load", "global", settings.REVORA_HOSTED_READY_TIMEOUT_S + 30.0
    )
    if not acquired:
        raise HostedConflictError(
            "Another model load is already in progress.",
            reason_code="load_in_progress",
        )

    op = {"state": "queued", "started": time.monotonic(), "owner": owner}
    _load_ops[name] = op
    try:
        op["state"] = "loading"
        try:
            response = await _get_client().post(
                endpoint_url("/api/generate"),
                json={
                    "model": name,
                    "prompt": "",
                    "stream": False,
                    "keep_alive": keep_alive_payload_value(
                        settings.REVORA_HOSTED_OLLAMA_KEEP_ALIVE
                    ),
                },
                headers=_headers(),
                timeout=settings.REVORA_HOSTED_OLLAMA_READ_TIMEOUT_S,
            )
        except Exception as exc:
            op["state"] = "failed"
            raise HostedUnavailableError(
                _safe_error(exc, "Hosted Ollama is unreachable."),
                reason_code="load_failed",
            )
        if response.status_code >= 400:
            op["state"] = "failed"
            if response.status_code in (401, 403):
                raise HostedAuthError("Hosted Ollama rejected the server credentials.")
            if response.status_code == 404:
                raise HostedNotFoundError(
                    f"Model '{name}' was not found on the hosted runtime.",
                    definitive=True, reason_code="model_not_found",
                )
            raise HostedUnavailableError(
                f"Hosted Ollama returned HTTP {response.status_code}.",
                reason_code="load_failed",
            )

        op["state"] = "verifying"
        deadline = time.monotonic() + settings.REVORA_HOSTED_READY_TIMEOUT_S
        delay = settings.REVORA_HOSTED_READY_POLL_INTERVAL_S
        cap = max(1.0, delay * 8)
        verified = False
        while time.monotonic() < deadline:
            snapshot = await get_snapshot(db, force=True)
            if any(m.model == name and m.loaded for m in snapshot.models):
                verified = True
                break
            await asyncio.sleep(delay)
            delay = min(delay * 2, cap)
        if verified:
            op["state"] = "loaded"
            _load_ops.pop(name, None)
            return {"status": "loaded", "model": name, "verified": True}
        op["state"] = "timeout"
        _load_ops.pop(name, None)
        return {
            "status": "timeout",
            "model": name,
            "verified": False,
            "reason_code": "load_timeout",
        }
    finally:
        await release_lease("load", "global", owner, mode)

class HostedConflictError(HostedError):
    code = "hosted_conflict"
    status_code = 409


# --- probe (structured, shared by monitor and readiness checks) -------------


@dataclass(frozen=True)
class HostedProbe:
    ok: bool
    category: str  # ok | transport | http | auth | config | invalid
    version: str | None = None
    status: int | None = None
    error: str | None = None


async def probe_ollama() -> HostedProbe:
    """Probe ``/api/version`` with a reported failure category.

    Only a ``transport`` failure is compatible with a suspended machine. Auth,
    configuration, HTTP status and malformed responses are reported separately
    so the monitor never treats them as proof that a wake is required.
    """
    try:
        endpoint_url("/api/version")
    except HostedError as exc:
        return HostedProbe(False, "config", error=exc.message)
    try:
        response, redirect_error = await _request_with_gateway_login(
            "GET", "/api/version",
            timeout=settings.REVORA_HOSTED_OLLAMA_DISCOVERY_TIMEOUT_S,
            headers=_headers(),
        )
    except httpx.TimeoutException:
        return HostedProbe(False, "transport", error="Hosted Ollama request timed out.")
    except httpx.HTTPError:
        return HostedProbe(False, "transport", error="Hosted Ollama is unreachable.")
    except Exception:
        return HostedProbe(False, "transport", error="Hosted Ollama is unreachable.")
    if response is None:
        return HostedProbe(False, "config", error=redirect_error)
    if response.status_code in (401, 403):
        return HostedProbe(False, "auth", status=response.status_code,
                           error="Hosted Ollama rejected the server credentials.")
    if response.status_code >= 500:
        return HostedProbe(False, "http", status=response.status_code,
                           error="Hosted Ollama is temporarily unavailable.")
    if response.status_code != 200:
        return HostedProbe(False, "http", status=response.status_code,
                           error=f"Hosted Ollama returned HTTP {response.status_code}.")
    try:
        data = response.json()
    except ValueError:
        return HostedProbe(False, "invalid", error="Hosted Ollama returned an invalid response.")
    version = data.get("version") if isinstance(data, dict) else None
    if not isinstance(version, str) or not version.strip():
        return HostedProbe(False, "invalid", error="Hosted Ollama returned an invalid response.")
    return HostedProbe(True, "ok", version=version.strip(), status=200)


# --- wake / recovery --------------------------------------------------------

_wake_lock = asyncio.Lock()
_waking = False
_last_wake_error: str | None = None


def _wake_configured() -> bool:
    return bool(
        settings.REVORA_HOSTED_WAKE_ENABLED
        and str(getattr(settings, "REVORA_HOSTED_WAKE_API_BASE_URL", "") or "").strip()
        and str(getattr(settings, "REVORA_HOSTED_WAKE_MACHINE_ID", "") or "").strip()
        and str(getattr(settings, "REVORA_HOSTED_WAKE_API_KEY", "") or "").strip()
    )


def _wake_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.REVORA_HOSTED_WAKE_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _wake_url(path: str) -> str:
    base = str(settings.REVORA_HOSTED_WAKE_API_BASE_URL).strip().rstrip("/")
    machine = quote(str(settings.REVORA_HOSTED_WAKE_MACHINE_ID).strip(), safe="")
    return f"{base}/v1/machines/{machine}{path}"


@dataclass(frozen=True)
class WakeResult:
    accepted: bool
    error: str | None = None
    retry_after: float | None = None
    conflict: bool = False


async def call_wake() -> WakeResult:
    """POST the wake endpoint once. Returns a structured result, never logs the key."""
    try:
        response = await _get_client().post(
            _wake_url("/wake"),
            headers=_wake_headers(),
            timeout=settings.REVORA_HOSTED_WAKE_TIMEOUT_S,
        )
    except Exception as exc:
        return WakeResult(False, error=_safe_error(exc, "Unable to reach the wake API."))
    if response.status_code in (200, 202):
        return WakeResult(True)
    if response.status_code == 409:
        code = None
        retry_after = None
        try:
            body = response.json()
            if isinstance(body, dict):
                code = body.get("code") or body.get("error")
                value = body.get("retryAfterSeconds")
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    retry_after = float(value)
        except ValueError:
            pass
        if code == "machine_cooldown":
            if retry_after is not None:
                global _cooldown_until
                _cooldown_until = time.time() + max(0.0, retry_after)
            return WakeResult(
                False,
                error="The hosted machine is cooling down. Try again later.",
                retry_after=retry_after,
            )
        # operation_conflict is retryable; the caller bounds the retries.
        return WakeResult(False, error="operation_conflict", conflict=True)
    if response.status_code in (401, 403):
        return WakeResult(False, error="The wake API rejected the server credentials.")
    return WakeResult(False, error=f"The wake API returned HTTP {response.status_code}.")


async def wait_for_ready() -> bool:
    """Bounded readiness polling with exponential backoff after a wake.

    A wake API response is never treated as readiness: Ollama itself must answer
    ``/api/version``. Stops on success, timeout or a terminal probe category.
    """
    deadline = time.monotonic() + settings.REVORA_HOSTED_READY_TIMEOUT_S
    delay = settings.REVORA_HOSTED_READY_POLL_INTERVAL_S
    cap = max(1.0, delay * 8)
    while time.monotonic() < deadline:
        probe = await probe_ollama()
        if probe.ok:
            invalidate_cache()
            _last_wake_error = None
            return True
        if probe.category in ("auth", "config"):
            _last_wake_error = probe.error
            return False
        await asyncio.sleep(delay)
        delay = min(delay * 2, cap)
    _last_wake_error = "The hosted machine did not become ready in time."
    return False


async def wake_and_wait_ready() -> bool:
    """Wake the machine and wait until Ollama is reachable (used by chat sends).

    Local single-flight: concurrent callers share one wake. Distributed dedup
    for session-driven wakes is owned by ``hosted_monitor``.
    """
    global _waking, _last_wake_error
    if not _wake_configured():
        return False
    async with _wake_lock:
        _waking = True
        try:
            deadline = time.monotonic() + settings.REVORA_HOSTED_READY_TIMEOUT_S
            result: WakeResult | None = None
            for _ in range(3):
                result = await call_wake()
                if result.accepted or not result.conflict:
                    break
                if time.monotonic() >= deadline:
                    break
                await asyncio.sleep(2.0)
            if result is None or not result.accepted:
                _last_wake_error = result.error if result else "Wake request failed."
                return False
            return await wait_for_ready()
        finally:
            _waking = False


@asynccontextmanager
async def activity_lease():
    """Hold an activity lease during inference so an idle pause cannot interrupt.

    Best-effort: a lease failure never fails the request. The lease is always
    released on exit (including cancellation). No-op when wake is disabled.
    """
    if not _wake_configured():
        yield
        return
    task_id = uuid.uuid4().hex
    url = _wake_url(f"/activity-leases/{task_id}")
    ttl = int(settings.REVORA_HOSTED_LEASE_TTL_S)
    try:
        await _get_client().put(
            url,
            json={"ttlSeconds": ttl},
            headers=_wake_headers(),
            timeout=settings.REVORA_HOSTED_WAKE_TIMEOUT_S,
        )
    except Exception as exc:
        logger.warning("hosted activity lease start failed: %s", type(exc).__name__)
    try:
        yield
    finally:
        try:
            await _get_client().delete(
                url,
                headers=_wake_headers(),
                timeout=settings.REVORA_HOSTED_WAKE_TIMEOUT_S,
            )
        except Exception as exc:
            logger.warning("hosted activity lease release failed: %s", type(exc).__name__)


def wake_status() -> dict[str, Any]:
    return {
        "enabled": bool(settings.REVORA_HOSTED_WAKE_ENABLED),
        "configured": _wake_configured(),
        "waking": _waking,
        "last_error": _last_wake_error,
        "cooldown_until": _cooldown_until_iso(),
    }
