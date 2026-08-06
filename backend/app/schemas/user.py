import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field


class UserBase(BaseModel):
    name: str = Field(..., max_length=100)
    email: EmailStr


class UserCreate(UserBase):
    password: str = Field(..., min_length=8)


class UserUpdate(BaseModel):
    name: str | None = None
    avatar_url: str | None = None
    default_provider: str | None = None
    settings: dict[str, Any] | None = None


class UserInDBBase(UserBase):
    id: uuid.UUID
    github_id: int | None = None
    github_username: str | None = None
    avatar_url: str | None = None
    role: str
    is_verified: bool
    default_provider: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class User(UserInDBBase):
    pass
