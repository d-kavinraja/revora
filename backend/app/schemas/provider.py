import uuid
from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel, Field


class ProviderRegistryRead(BaseModel):
    id: uuid.UUID
    name: str
    display_name: str
    slug: str
    litellm_provider: str
    api_key_prefix: Optional[str] = None
    api_key_min_length: int = 15
    base_url_template: Optional[str] = None
    default_model: str
    timeout_seconds: int = 60
    max_retries: int = 3
    priority: int = 0
    supports_streaming: bool = True
    supports_vision: bool = False
    supports_function_calling: bool = False
    supports_reasoning: bool = False
    is_enabled: bool = True
    extra_config: Dict[str, Any] = {}
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ProviderRegistryUpdate(BaseModel):
    display_name: Optional[str] = None
    base_url_template: Optional[str] = None
    default_model: Optional[str] = None
    timeout_seconds: Optional[int] = None
    max_retries: Optional[int] = None
    priority: Optional[int] = None
    is_enabled: Optional[bool] = None
    extra_config: Optional[Dict[str, Any]] = None


class ProviderToggle(BaseModel):
    is_enabled: bool


class ProviderCapabilities(BaseModel):
    providers: Dict[str, List[str]]
