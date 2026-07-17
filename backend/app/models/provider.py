from typing import Optional, Dict, Any
from sqlalchemy import String, Boolean, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSON_TYPE


class ProviderRegistry(Base):
    """DB-backed provider registry. Replaces hardcoded PROVIDER_PRIORITY."""

    __tablename__ = "provider_registry"

    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    # LiteLLM mapping
    litellm_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    api_key_prefix: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    api_key_min_length: Mapped[int] = mapped_column(Integer, default=15)

    # Configuration
    base_url_template: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    default_model: Mapped[str] = mapped_column(String(100), nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=60)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    priority: Mapped[int] = mapped_column(Integer, default=0)

    # Capabilities
    supports_streaming: Mapped[bool] = mapped_column(Boolean, default=True)
    supports_vision: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_function_calling: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_reasoning: Mapped[bool] = mapped_column(Boolean, default=False)

    # Status
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    extra_config: Mapped[Dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
