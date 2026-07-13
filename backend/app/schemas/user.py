import uuid
from typing import Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field

class UserBase(BaseModel):
    name: str = Field(..., max_length=100)
    email: EmailStr

class UserCreate(UserBase):
    password: str = Field(..., min_length=8)

class UserUpdate(BaseModel):
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    default_provider: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None

class UserInDBBase(UserBase):
    id: uuid.UUID
    github_id: Optional[int] = None
    github_username: Optional[str] = None
    avatar_url: Optional[str] = None
    role: str
    is_verified: bool
    default_provider: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

class User(UserInDBBase):
    pass
