"""Platform settings service (phases 5–6, §11–§12).

Maintenance state lives in `platform_settings['maintenance']` (the DB row is
the source of truth) and is read through a 5-second in-process TTL cache so
the enforcement middleware and the worker claim gate add no per-request DB
round-trip. Admin writes go through `set_maintenance` (write-through cache);
the CLI writes the row directly, so every process converges within one TTL
window (§12.1) and recovery never needs a redeploy (§12.2 / B25).

Feature flags (§11) share the same TTL-cached, default-tolerant read path:
a missing `feature_flags` row means `enabled`, so the SQLite `create_all`
dev path (no seed migration) behaves exactly like a fresh deploy.

All reads are fail-open: a missing row or an unreachable DB yields the
default state (maintenance disabled / flags enabled), so a database hiccup
can never block the platform that is supposed to keep serving.
"""

import logging
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.platform import (
    FEATURE_FLAG_KEYS,
    FLAG_STATUSES,
    FeatureFlag,
    PlatformSetting,
)

logger = logging.getLogger(__name__)

MAINTENANCE_KEY = "maintenance"
CACHE_TTL_SECONDS = 5.0

#: Full internal state shape (§12.1). `reason` and `changed_by` are internal;
#: the public payload is built via `public_state`.
DEFAULT_MAINTENANCE: dict[str, Any] = {
    "enabled": False,
    "title": None,
    "message": None,
    "expected_return_at": None,
    "reason": None,
    "changed_by": None,
    "changed_at": None,
    "version": 0,
}

#: Fields the admin PUT may write.
EDITABLE_FIELDS = ("enabled", "title", "message", "expected_return_at", "reason")


def default_flag() -> dict[str, Any]:
    """Default-tolerant flag state: missing row ⇒ enabled, no message."""
    return {"status": "enabled", "message": None}


def public_state(value: dict[str, Any]) -> dict[str, Any]:
    """User-facing maintenance payload (never exposes `reason`/actor)."""
    return {
        "enabled": bool(value.get("enabled")),
        "title": value.get("title"),
        "message": value.get("message"),
        "expected_return_at": value.get("expected_return_at"),
    }


def _normalize(raw: dict[str, Any] | None, version: int = 0) -> dict[str, Any]:
    """Merge a stored JSON value over the defaults, coercing types."""
    value = dict(DEFAULT_MAINTENANCE)
    if isinstance(raw, dict):
        value["enabled"] = bool(raw.get("enabled", False))
        for key in (
            "title",
            "message",
            "expected_return_at",
            "reason",
            "changed_by",
            "changed_at",
        ):
            item = raw.get(key)
            if item is not None:
                value[key] = str(item)
    value["version"] = int(version or 0)
    return value


class PlatformSettingsService:
    """TTL-cached reader / write-through writer for platform settings."""

    def __init__(self) -> None:
        self.db_factory = AsyncSessionLocal
        self._cache: dict[str, Any] | None = None
        self._cache_at: float = 0.0
        self._flags_cache: dict[str, dict[str, Any]] | None = None
        self._flags_cache_at: float = 0.0

    # -- cache plumbing ----------------------------------------------------

    def clear_cache(self) -> None:
        self._cache = None
        self._cache_at = 0.0
        self._flags_cache = None
        self._flags_cache_at = 0.0

    def _cached(self) -> dict[str, Any] | None:
        if self._cache is None:
            return None
        if (time.monotonic() - self._cache_at) >= CACHE_TTL_SECONDS:
            return None
        return self._cache

    def _store(self, value: dict[str, Any]) -> None:
        self._cache = dict(value)
        self._cache_at = time.monotonic()

    def _cached_flags(self) -> dict[str, dict[str, Any]] | None:
        if self._flags_cache is None:
            return None
        if (time.monotonic() - self._flags_cache_at) >= CACHE_TTL_SECONDS:
            return None
        return self._flags_cache

    def _store_flags(self, value: dict[str, dict[str, Any]]) -> None:
        self._flags_cache = {key: dict(item) for key, item in value.items()}
        self._flags_cache_at = time.monotonic()

    # -- reads -------------------------------------------------------------

    async def _read_row(self, db: AsyncSession) -> tuple[dict[str, Any] | None, int]:
        result = await db.execute(
            select(PlatformSetting).where(PlatformSetting.key == MAINTENANCE_KEY)
        )
        row = result.scalars().first()
        if row is None:
            return None, 0
        raw = row.value if isinstance(row.value, dict) else None
        return raw, int(row.version or 1)

    async def get_maintenance(
        self, db: AsyncSession | None = None, *, force: bool = False
    ) -> dict[str, Any]:
        """Current maintenance state (internal shape, incl. `version`).

        `db` reads through the caller's session (admin GET); without it the
        service falls back to `db_factory` and finally to the fail-open
        default (disabled). Results are cached for `CACHE_TTL_SECONDS`.
        """
        if not force:
            cached = self._cached()
            if cached is not None:
                return dict(cached)

        try:
            if db is not None:
                raw, version = await self._read_row(db)
            elif self.db_factory is not None:
                async with self.db_factory() as session:
                    raw, version = await self._read_row(session)
            else:
                return dict(DEFAULT_MAINTENANCE)
        except Exception:
            logger.warning(
                "Maintenance state read failed; assuming disabled", exc_info=True
            )
            # A failed SELECT leaves the caller's transaction aborted on
            # Postgres — roll back so the claim path can continue safely.
            if db is not None:
                try:
                    await db.rollback()
                except Exception:
                    pass
            return dict(DEFAULT_MAINTENANCE)

        value = _normalize(raw, version)
        self._store(value)
        return dict(value)

    async def is_enabled(self, db: AsyncSession | None = None) -> bool:
        state = await self.get_maintenance(db)
        return bool(state.get("enabled"))

    # -- feature flags (§11) ----------------------------------------------

    async def _read_flags(self, db: AsyncSession) -> dict[str, dict[str, Any]]:
        result = await db.execute(select(FeatureFlag))
        rows = {row.key: row for row in result.scalars().all()}
        flags: dict[str, dict[str, Any]] = {}
        for key in FEATURE_FLAG_KEYS:
            row = rows.get(key)
            if row is None:
                flags[key] = default_flag()
            else:
                flags[key] = {
                    "status": row.status or "enabled",
                    "message": row.message,
                }
        return flags

    async def get_flags(
        self, db: AsyncSession | None = None, *, force: bool = False
    ) -> dict[str, dict[str, Any]]:
        """All canonical flags with status + message (default-tolerant).

        Same fail-open contract as `get_maintenance`: an unreachable DB or a
        missing row yields `{"status": "enabled", "message": None}`.
        """
        if not force:
            cached = self._cached_flags()
            if cached is not None:
                return {key: dict(item) for key, item in cached.items()}

        try:
            if db is not None:
                flags = await self._read_flags(db)
            elif self.db_factory is not None:
                async with self.db_factory() as session:
                    flags = await self._read_flags(session)
            else:
                flags = {key: default_flag() for key in FEATURE_FLAG_KEYS}
        except Exception:
            logger.warning(
                "Feature flag read failed; assuming enabled defaults",
                exc_info=True,
            )
            if db is not None:
                try:
                    await db.rollback()
                except Exception:
                    pass
            flags = {key: default_flag() for key in FEATURE_FLAG_KEYS}

        self._store_flags(flags)
        return {key: dict(item) for key, item in flags.items()}

    async def get_flag(
        self, key: str, db: AsyncSession | None = None, *, force: bool = False
    ) -> dict[str, Any]:
        flags = await self.get_flags(db, force=force)
        return dict(flags.get(key, default_flag()))

    async def is_feature_enabled(self, key: str, db: AsyncSession | None = None) -> bool:
        flag = await self.get_flag(key, db)
        return flag.get("status") == "enabled"

    # -- writes ------------------------------------------------------------

    async def set_maintenance(
        self,
        db: AsyncSession,
        updates: dict[str, Any],
        *,
        admin_id: Any = None,
        expected_version: int | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], int | None]:
        """Apply a whitelisted update and prime the cache (write-through).

        Returns `(new_state, prior_state, conflict_version)`. A non-None
        `conflict_version` means the caller's `expected_version` was stale —
        nothing was written. The caller commits (and audits) the session.
        """
        # Sessions are autoflush=False; make any pending writes in this
        # session visible to the read without forcing a commit.
        await db.flush()
        result = await db.execute(
            select(PlatformSetting).where(PlatformSetting.key == MAINTENANCE_KEY)
        )
        row = result.scalars().first()
        row_version = int(row.version or 1) if row is not None else 0
        prior = _normalize(
            (row.value if row is not None and isinstance(row.value, dict) else None),
            row_version,
        )

        if expected_version is not None and int(expected_version) != row_version:
            return dict(prior), dict(prior), row_version

        new_value = dict(prior)
        for key in EDITABLE_FIELDS:
            if key in updates:
                new_value[key] = updates[key]
        new_value["enabled"] = bool(new_value.get("enabled"))
        new_value["changed_at"] = datetime.now(UTC).isoformat()
        new_value["changed_by"] = (
            str(admin_id) if admin_id is not None else "system"
        )
        new_value["version"] = row_version + 1

        if row is None:
            row = PlatformSetting(
                key=MAINTENANCE_KEY,
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

        self._store(new_value)
        return dict(new_value), prior, None

    async def set_flag(
        self,
        db: AsyncSession,
        key: str,
        *,
        status: str,
        message: str | None = None,
        admin_id: Any = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Upsert one flag row; returns `(new_state, prior_state)`.

        Validates the canonical key/status vocabulary (ValueError otherwise)
        and invalidates the cache so the next read — including the immediate
        post-write user request — sees the change. The caller commits/audits.
        """
        if key not in FEATURE_FLAG_KEYS:
            raise ValueError(f"Unknown feature flag key '{key}'.")
        if status not in FLAG_STATUSES:
            raise ValueError(f"Invalid feature flag status '{status}'.")

        # Sessions are autoflush=False; see `set_maintenance`.
        await db.flush()
        result = await db.execute(select(FeatureFlag).where(FeatureFlag.key == key))
        row = result.scalars().first()
        prior = (
            {"status": row.status or "enabled", "message": row.message}
            if row is not None
            else default_flag()
        )

        if row is None:
            row = FeatureFlag(
                key=key,
                status=status,
                message=message,
                updated_by=admin_id,
            )
            db.add(row)
        else:
            row.status = status
            row.message = message
            row.updated_by = admin_id
            db.add(row)

        new_state = {"status": status, "message": message}
        # Invalidate (not prime): the cached map spans every flag.
        self._flags_cache = None
        self._flags_cache_at = 0.0
        return new_state, prior


platform_settings_service = PlatformSettingsService()
