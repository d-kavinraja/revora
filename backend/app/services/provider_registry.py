from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.provider import ProviderRegistry

#: Provider statuses that block new use (key addition, mapping, reviews).
BLOCKED_STATUSES = ("disabled", "under_testing", "coming_soon", "unavailable")
VALID_STATUSES = ("available", *BLOCKED_STATUSES)


class ProviderUnavailableError(Exception):
    """Raised when an explicitly mapped provider is blocked (fail fast, D2).

    The mapping is never cleared and no other provider is substituted.
    """

    def __init__(self, provider: str, message: str | None = None):
        self.provider = provider
        self.message = message or (
            f"Provider '{provider}' is not available for new reviews."
        )
        super().__init__(self.message)


class ProviderRegistryService:
    async def get_all(self, db: AsyncSession) -> list[ProviderRegistry]:
        result = await db.execute(
            select(ProviderRegistry).order_by(ProviderRegistry.priority)
        )
        return list(result.scalars().all())

    async def get_enabled(self, db: AsyncSession) -> list[ProviderRegistry]:
        result = await db.execute(
            select(ProviderRegistry)
            .where(ProviderRegistry.is_enabled == True)
            .order_by(ProviderRegistry.priority)
        )
        return list(result.scalars().all())

    async def get_usable(self, db: AsyncSession) -> list[ProviderRegistry]:
        """Enabled providers with `available` status — the only ones allowed
        for new keys, mappings, model selection and reviews (phase 4, §9.3).
        """
        result = await db.execute(
            select(ProviderRegistry)
            .where(ProviderRegistry.is_enabled == True)
            .where(ProviderRegistry.status == "available")
            .order_by(ProviderRegistry.priority)
        )
        return list(result.scalars().all())

    async def get_by_slug(self, db: AsyncSession, slug: str) -> ProviderRegistry | None:
        result = await db.execute(
            select(ProviderRegistry).where(ProviderRegistry.slug == slug)
        )
        return result.scalars().first()

    async def get_by_name(self, db: AsyncSession, name: str) -> ProviderRegistry | None:
        result = await db.execute(
            select(ProviderRegistry).where(ProviderRegistry.name == name)
        )
        return result.scalars().first()

    async def get_by_identifier(
        self, db: AsyncSession, identifier: str
    ) -> ProviderRegistry | None:
        """Look up a provider by slug or name (mappings store either form)."""
        return await self.get_by_slug(db, identifier) or await self.get_by_name(
            db, identifier
        )

    async def usability(
        self, db: AsyncSession, identifier: str
    ) -> tuple[bool, ProviderRegistry | None]:
        """Return `(usable, provider)` for a mapping/selection target.

        `usable` requires the row to exist, `is_enabled` true and status
        `available`. Zero-state (no controls flipped) is always usable.
        """
        provider = await self.get_by_identifier(db, identifier)
        if provider is None:
            return False, None
        usable = bool(provider.is_enabled) and provider.status == "available"
        return usable, provider

    async def ensure_usable(self, db: AsyncSession, identifier: str) -> None:
        """Raise `ProviderUnavailableError` unless the provider is usable."""
        usable, provider = await self.usability(db, identifier)
        if not usable:
            message = None
            if provider is not None and provider.status_message:
                message = provider.status_message
            raise ProviderUnavailableError(identifier, message)

    async def update(
        self, db: AsyncSession, slug: str, data: dict
    ) -> ProviderRegistry | None:
        provider = await self.get_by_slug(db, slug)
        if not provider:
            return None
        data = dict(data)
        self._apply_consistency(provider, data)
        for key, value in data.items():
            if value is not None and hasattr(provider, key):
                setattr(provider, key, value)
        db.add(provider)
        await db.commit()
        await db.refresh(provider)
        return provider

    @staticmethod
    def _apply_consistency(provider: ProviderRegistry, changes: dict) -> None:
        """Keep `is_enabled=false ⇔ status='disabled'` consistent (§9.1).

        Mutates `changes` in place so callers can persist effective values.
        """
        if changes.get("status") == "disabled":
            changes["is_enabled"] = False
        elif changes.get("is_enabled") is False:
            changes["status"] = "disabled"
        elif (
            changes.get("is_enabled") is True
            and changes.get("status") is None
            and provider.status == "disabled"
        ):
            changes["status"] = "available"

    async def apply_admin_update(
        self,
        db: AsyncSession,
        provider: ProviderRegistry,
        changes: dict,
    ) -> tuple[ProviderRegistry, dict]:
        """Apply a whitelisted admin update transactionally (no commit).

        Returns `(provider, effective_changes)` where `effective_changes`
        contains only fields whose values actually changed.
        """
        original = {
            "status": provider.status,
            "status_message": provider.status_message,
            "status_expires_at": provider.status_expires_at,
            "is_enabled": provider.is_enabled,
            "allow_key_addition": provider.allow_key_addition,
        }
        self._apply_consistency(provider, changes)
        for key, value in changes.items():
            setattr(provider, key, value)
        db.add(provider)
        effective = {
            key: value
            for key, value in changes.items()
            if original.get(key) != value
        }
        return provider, effective

    async def toggle(
        self, db: AsyncSession, slug: str, enabled: bool
    ) -> ProviderRegistry | None:
        provider = await self.get_by_slug(db, slug)
        if not provider:
            return None
        changes: dict = {"is_enabled": enabled}
        self._apply_consistency(provider, changes)
        provider.is_enabled = changes["is_enabled"]
        provider.status = changes.get("status", provider.status)
        db.add(provider)
        await db.commit()
        await db.refresh(provider)
        return provider

    async def get_capabilities_matrix(self, db: AsyncSession) -> dict[str, list[str]]:
        providers = await self.get_all(db)
        matrix = {}
        for p in providers:
            caps = []
            if p.supports_streaming:
                caps.append("streaming")
            if p.supports_vision:
                caps.append("vision")
            if p.supports_function_calling:
                caps.append("function_calling")
            if p.supports_reasoning:
                caps.append("reasoning")
            matrix[p.slug] = caps
        return matrix

    async def get_litellm_provider_map(self, db: AsyncSession) -> dict[str, str]:
        providers = await self.get_usable(db)
        return {p.name: p.litellm_provider for p in providers}


provider_registry_service = ProviderRegistryService()
