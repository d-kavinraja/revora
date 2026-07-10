import uuid
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.api_key import ApiKey
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
        """Fetch the valid key for a provider and decrypt it."""
        result = await db.execute(
            select(ApiKey)
            .where(ApiKey.user_id == user_id)
            .where(ApiKey.provider == provider)
            .where(ApiKey.is_valid == True)
        )
        key_obj = result.scalars().first()
        if not key_obj:
            return None
            
        return encryption_service.decrypt(key_obj.encrypted_key)

api_key_service = ApiKeyService()
