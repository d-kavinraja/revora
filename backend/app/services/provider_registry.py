from typing import List, Optional, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.provider import ProviderRegistry


class ProviderRegistryService:
    async def get_all(self, db: AsyncSession) -> List[ProviderRegistry]:
        result = await db.execute(select(ProviderRegistry).order_by(ProviderRegistry.priority))
        return list(result.scalars().all())

    async def get_enabled(self, db: AsyncSession) -> List[ProviderRegistry]:
        result = await db.execute(
            select(ProviderRegistry)
            .where(ProviderRegistry.is_enabled == True)
            .order_by(ProviderRegistry.priority)
        )
        return list(result.scalars().all())

    async def get_by_slug(self, db: AsyncSession, slug: str) -> Optional[ProviderRegistry]:
        result = await db.execute(
            select(ProviderRegistry).where(ProviderRegistry.slug == slug)
        )
        return result.scalars().first()

    async def get_by_name(self, db: AsyncSession, name: str) -> Optional[ProviderRegistry]:
        result = await db.execute(
            select(ProviderRegistry).where(ProviderRegistry.name == name)
        )
        return result.scalars().first()

    async def update(self, db: AsyncSession, slug: str, data: dict) -> Optional[ProviderRegistry]:
        provider = await self.get_by_slug(db, slug)
        if not provider:
            return None
        for key, value in data.items():
            if value is not None and hasattr(provider, key):
                setattr(provider, key, value)
        db.add(provider)
        await db.commit()
        await db.refresh(provider)
        return provider

    async def toggle(self, db: AsyncSession, slug: str, enabled: bool) -> Optional[ProviderRegistry]:
        provider = await self.get_by_slug(db, slug)
        if not provider:
            return None
        provider.is_enabled = enabled
        db.add(provider)
        await db.commit()
        await db.refresh(provider)
        return provider

    async def get_capabilities_matrix(self, db: AsyncSession) -> Dict[str, List[str]]:
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

    async def get_litellm_provider_map(self, db: AsyncSession) -> Dict[str, str]:
        providers = await self.get_enabled(db)
        return {p.name: p.litellm_provider for p in providers}


provider_registry_service = ProviderRegistryService()
