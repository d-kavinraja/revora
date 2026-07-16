"""SQLAlchemy ORM models for the Prompt Builder Engine."""

import uuid
from typing import Optional, Dict, Any
from sqlalchemy import String, Text, Integer, Float, Boolean, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, JSON_TYPE


class PromptTemplate(Base):
    """Prompt template definitions."""
    __tablename__ = "prompt_templates"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    review_type: Mapped[str] = mapped_column(String(50), nullable=False)
    system_prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    sections_config: Mapped[Dict[str, Any]] = mapped_column(JSON_TYPE, default=dict, server_default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    extra_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON_TYPE, default=dict, server_default="{}")


class PromptVersionRecord(Base):
    """Prompt version records for A/B testing and rollback."""
    __tablename__ = "prompt_versions"

    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompt_templates.id", ondelete="CASCADE"), index=True, nullable=False
    )
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    sections_config: Mapped[Dict[str, Any]] = mapped_column(JSON_TYPE, default=dict, server_default="{}")
    token_budget: Mapped[int] = mapped_column(Integer, default=10000, server_default="10000")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    extra_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON_TYPE, default=dict, server_default="{}")


class PromptCacheRecord(Base):
    """Cached prompt data for fast retrieval."""
    __tablename__ = "prompt_cache"

    cache_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    sections_data: Mapped[Dict[str, Any]] = mapped_column(JSON_TYPE, default=dict, server_default="{}")
    ttl_seconds: Mapped[int] = mapped_column(Integer, default=300, server_default="300")
    hit_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class PromptMetric(Base):
    """Prompt build metrics for observability."""
    __tablename__ = "prompt_metrics"

    prompt_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    review_type: Mapped[str] = mapped_column(String(50), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    compression_ratio: Mapped[float] = mapped_column(Float, default=1.0, server_default="1.0")
    build_time_ms: Mapped[float] = mapped_column(Float, default=0.0, server_default="0.0")
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, server_default="0.0")
    sections_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    files_included: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    extra_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON_TYPE, default=dict, server_default="{}")


class TokenUsageRecord(Base):
    """Token usage tracking for cost analysis."""
    __tablename__ = "token_usage"

    prompt_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    review_type: Mapped[str] = mapped_column(String(50), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    budget_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    budget_used: Mapped[float] = mapped_column(Float, nullable=False)
    section_usage: Mapped[Dict[str, Any]] = mapped_column(JSON_TYPE, default=dict, server_default="{}")
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, server_default="0.0")
