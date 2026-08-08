import datetime
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.discovery.base import BaseDiscoveryAdapter
from app.ai.discovery.openrouter import OpenRouterDiscoveryAdapter
from app.models.api_key import ApiKey
from app.models.discovered_model import DiscoveredModel
from app.core.security import encryption_service


class DiscoveryEngineService:
    def __init__(self):
        self.adapters: dict[str, BaseDiscoveryAdapter] = {
            "openrouter": OpenRouterDiscoveryAdapter(),
        }

    async def sync_provider_models(self, db: AsyncSession, provider_slug: str, force: bool = False) -> list[DiscoveredModel]:
        """
        Synchronizes models for a given provider. 
        If force is False, only syncs if last_synced_at is older than 24 hours.
        Returns the current list of DiscoveredModels for this provider from the DB.
        """
        if provider_slug not in self.adapters:
            # We fallback to static list or no-op if adapter not found
            return await self.get_cached_models(db, provider_slug)

        # Check if we need to sync
        if not force:
            result = await db.execute(
                select(DiscoveredModel)
                .where(DiscoveredModel.provider_slug == provider_slug)
                .order_by(DiscoveredModel.last_synced_at.desc())
                .limit(1)
            )
            latest = result.scalars().first()
            if latest:
                age = datetime.datetime.now(datetime.UTC) - latest.last_synced_at
                if age.total_seconds() < 86400: # 24 hours
                    return await self.get_cached_models(db, provider_slug)

        # Find a valid API key for this provider
        result = await db.execute(
            select(ApiKey).where(ApiKey.provider == provider_slug)
        )
        api_keys = result.scalars().all()
        if not api_keys:
            raise ValueError(f"No API keys configured for provider {provider_slug}")
            
        api_key_obj = api_keys[0]
        raw_key = encryption_service.decrypt(api_key_obj.encrypted_key)
        
        adapter = self.adapters[provider_slug]
        
        try:
            discovered_models = await adapter.fetch_models(raw_key)
        except Exception as e:
            raise RuntimeError(f"Failed to fetch models from {provider_slug}: {str(e)}") from e

        if not discovered_models:
            raise RuntimeError(f"No valid/free models found for {provider_slug}")

        # Clear existing cached models for this provider
        await db.execute(
            delete(DiscoveredModel).where(DiscoveredModel.provider_slug == provider_slug)
        )
        
        # Insert the newly discovered models
        db.add_all(discovered_models)
        await db.commit()
        
        return await self.get_cached_models(db, provider_slug)

    async def get_cached_models(self, db: AsyncSession, provider_slug: str) -> list[DiscoveredModel]:
        result = await db.execute(
            select(DiscoveredModel)
            .where(DiscoveredModel.provider_slug == provider_slug)
            .order_by(DiscoveredModel.display_name)
        )
        return list(result.scalars().all())


discovery_engine = DiscoveryEngineService()
