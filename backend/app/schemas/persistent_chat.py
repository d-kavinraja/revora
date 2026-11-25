"""API contracts for stored Chat conversations."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ChatModeSettingsRead(BaseModel):
    temporary_enabled: bool
    persistent_enabled: bool
    temporary_message: str | None = None
    persistent_message: str | None = None
    version: int = 0


class ChatModeSettingsUpdate(BaseModel):
    temporary_enabled: bool
    persistent_enabled: bool
    temporary_message: str | None = Field(default=None, max_length=500)
    persistent_message: str | None = Field(default=None, max_length=500)
    version: int


class PersistentMessageRead(BaseModel):
    id: uuid.UUID
    position: int
    role: Literal["user", "assistant"]
    content: str
    status: str
    model: str | None = None
    finish_reason: str | None = None
    created_at: datetime


class PersistentConversationRead(BaseModel):
    id: uuid.UUID
    title: str
    model: str | None = None
    created_at: datetime
    updated_at: datetime
    messages: list[PersistentMessageRead]


class PersistentConversationSummary(BaseModel):
    id: uuid.UUID
    title: str
    model: str | None = None
    created_at: datetime
    updated_at: datetime
    message_count: int


class PersistentConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=128)


class PersistentConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class PersistentMessageCreate(BaseModel):
    model: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=200_000)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=16_384)
    reasoning_effort: Literal["low", "medium", "high", "max"] | None = None


class PersistentMessageEdit(BaseModel):
    content: str = Field(min_length=1, max_length=200_000)
    model: str | None = Field(default=None, max_length=128)


class PersistentRegenerate(BaseModel):
    model: str | None = Field(default=None, max_length=128)
