import uuid
from typing import Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field

class ApiKeyBase(BaseModel):
    provider: str = Field(..., max_length=50)
    label: str = Field(..., max_length=100)

class ApiKeyCreate(ApiKeyBase):
    api_key: str = Field(..., description="The raw API key to be encrypted")

class ApiKeyUpdate(BaseModel):
    label: Optional[str] = Field(None, max_length=100)
    api_key: Optional[str] = Field(None, description="The new raw API key")
    is_valid: Optional[bool] = None

class ApiKeyInDBBase(ApiKeyBase):
    id: uuid.UUID
    user_id: uuid.UUID
    is_valid: bool
    last_used_at: Optional[datetime] = None
    created_at: datetime
    
    model_config = {"from_attributes": True}

class ApiKey(ApiKeyInDBBase):
    masked_key: str = Field(..., description="Masked version of the key for UI")

    @classmethod
    def from_orm_with_mask(cls, obj: Any, raw_key: str):
        masked = f"{raw_key[:4]}...{raw_key[-4:]}" if len(raw_key) > 8 else "***"
        data = {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
        data["masked_key"] = masked
        return cls(**data)
