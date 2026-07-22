import uuid
from typing import List, Optional, Dict
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.api_key import ApiKey
from app.models.health import ApiKeyHealth
from app.schemas.api_key import ApiKeyCreate, ApiKeyUpdate
from app.core.security import encryption_service


class ApiKeyService:
    async def get_all_for_user(self, db: AsyncSession, user_id: uuid.UUID) -> List[ApiKey]:
        result = await db.execute(select(ApiKey).where(ApiKey.user_id == user_id))
        return list(result.scalars().all())

    async def get_by_id(self, db: AsyncSession, key_id: uuid.UUID) -> Optional[ApiKey]:
        return await db.get(ApiKey, key_id)

    async def create(self, db: AsyncSession, user_id: uuid.UUID, key_in: ApiKeyCreate) -> ApiKey:
        encrypted_key = encryption_service.encrypt(key_in.api_key)
        db_obj = ApiKey(
            user_id=user_id,
            provider=key_in.provider,
            label=key_in.label,
            encrypted_key=encrypted_key,
        )
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def update(self, db: AsyncSession, db_obj: ApiKey, obj_in: ApiKeyUpdate) -> ApiKey:
        update_data = obj_in.model_dump(exclude_unset=True)
        if "api_key" in update_data and update_data["api_key"]:
            db_obj.encrypted_key = encryption_service.encrypt(update_data.pop("api_key"))
        for field, value in update_data.items():
            setattr(db_obj, field, value)
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def delete(self, db: AsyncSession, db_obj: ApiKey) -> None:
        await db.delete(db_obj)
        await db.commit()

    async def get_decrypted_key(self, db: AsyncSession, user_id: uuid.UUID, provider: str) -> Optional[str]:
        """Get decrypted API key, preferring the most recently used valid key."""
        result = await db.execute(
            select(ApiKey)
            .where(ApiKey.user_id == user_id)
            .where(ApiKey.provider.ilike(provider))
            .where(ApiKey.is_valid == True)
            .order_by(ApiKey.last_used_at.desc().nulls_last())
        )
        key_obj = result.scalars().first()
        if not key_obj:
            return None
        return encryption_service.decrypt(key_obj.encrypted_key)

    async def get_all_decrypted_keys(self, db: AsyncSession, user_id: uuid.UUID, provider: str) -> list:
        """Get ALL decrypted API keys for a provider (for retry logic)."""
        result = await db.execute(
            select(ApiKey)
            .where(ApiKey.user_id == user_id)
            .where(ApiKey.provider.ilike(provider))
            .where(ApiKey.is_valid == True)
            .order_by(ApiKey.last_used_at.desc().nulls_last())
        )
        keys = result.scalars().all()
        decrypted = []
        for k in keys:
            try:
                decrypted.append((k.id, encryption_service.decrypt(k.encrypted_key)))
            except Exception:
                continue
        return decrypted

    async def get_usable_key(self, db: AsyncSession, user_id: uuid.UUID, provider: str) -> Optional[ApiKey]:
        result = await db.execute(
            select(ApiKey)
            .where(ApiKey.user_id == user_id)
            .where(ApiKey.provider.ilike(provider))
            .where(ApiKey.is_valid == True)
            .order_by(ApiKey.last_used_at.desc().nulls_last())
        )
        return result.scalars().first()

    async def get_all_usable_keys(self, db: AsyncSession, user_id: uuid.UUID) -> Dict[str, ApiKey]:
        result = await db.execute(
            select(ApiKey)
            .where(ApiKey.user_id == user_id)
            .where(ApiKey.is_valid == True)
        )
        keys = result.scalars().all()
        provider_keys = {}
        for key in keys:
            if key.provider not in provider_keys:
                provider_keys[key.provider] = key
        return provider_keys

    async def rotate(self, db: AsyncSession, key_id: uuid.UUID, new_key: str) -> Optional[ApiKey]:
        db_key = await self.get_by_id(db, key_id)
        if not db_key:
            return None
        db_key.encrypted_key = encryption_service.encrypt(new_key)
        db_key.is_valid = True
        db.add(db_key)
        await db.commit()
        await db.refresh(db_key)
        return db_key

    async def record_health(
        self,
        db: AsyncSession,
        key_id: uuid.UUID,
        status: str,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        latency_ms: Optional[float] = None,
    ) -> ApiKeyHealth:
        health = ApiKeyHealth(
            key_id=key_id,
            status=status,
            error_type=error_type,
            error_message=error_message,
            latency_ms=latency_ms,
            checked_at=datetime.now(timezone.utc),
        )
        db.add(health)
        await db.commit()
        await db.refresh(health)
        return health

    async def get_health_history(self, db: AsyncSession, key_id: uuid.UUID, limit: int = 10) -> List[ApiKeyHealth]:
        result = await db.execute(
            select(ApiKeyHealth)
            .where(ApiKeyHealth.key_id == key_id)
            .order_by(ApiKeyHealth.checked_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def mark_last_used(self, db: AsyncSession, key_id: uuid.UUID) -> None:
        db_key = await self.get_by_id(db, key_id)
        if db_key:
            db_key.last_used_at = datetime.now(timezone.utc)
            db.add(db_key)
            await db.commit()


api_key_service = ApiKeyService()


