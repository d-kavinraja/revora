import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ProviderRegistryRead(BaseModel):
    id: uuid.UUID
    name: str
    display_name: str
    slug: str
    litellm_provider: str
    api_key_prefix: str | None = None
    api_key_min_length: int = 15
    base_url_template: str | None = None
    default_model: str
    timeout_seconds: int = 300
    max_retries: int = 3
    priority: int = 0
    supports_streaming: bool = True
    supports_vision: bool = False
    supports_function_calling: bool = False
    supports_reasoning: bool = False
    is_enabled: bool = True
    extra_config: dict[str, Any] = {}
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class ProviderRegistryUpdate(BaseModel):
    display_name: str | None = None
    base_url_template: str | None = None
    default_model: str | None = None
    timeout_seconds: int | None = None
    max_retries: int | None = None
    priority: int | None = None
    is_enabled: bool | None = None
    extra_config: dict[str, Any] | None = None


class ProviderToggle(BaseModel):
    is_enabled: bool


class ProviderCapabilities(BaseModel):
    matrix: dict[str, list[str]]


class DiscoveredModelRead(BaseModel):
    id: uuid.UUID
    provider_slug: str
    model_id: str
    display_name: str
    context_window: int | None = None
    is_free: bool
    description: str | None = None
    last_synced_at: datetime
    
    model_config = ConfigDict(from_attributes=True)
