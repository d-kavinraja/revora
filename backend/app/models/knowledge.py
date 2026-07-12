import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy import String, Text, Boolean, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base


class RepositoryKnowledge(Base):
    __tablename__ = "repository_knowledge"

    repo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True, nullable=False)
    knowledge_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    extra_metadata: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class RepositoryRule(Base):
    __tablename__ = "repository_rules"

    repo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True, nullable=False)
    rule_type: Mapped[str] = mapped_column(String(50), nullable=False)
    rule_text: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class RepositoryIndex(Base):
    __tablename__ = "repository_indexes"

    repo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True, nullable=False)
    index_data: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    graphs: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    commit_sha: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)


class RepositoryIntelligence(Base):
    __tablename__ = "repository_intelligence"

    repo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True, nullable=False)
    intelligence_data: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    commit_sha: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)


class ReviewEvent(Base):
    __tablename__ = "review_events"

    review_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    stage: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metrics: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    progress: Mapped[Optional[float]] = mapped_column(nullable=True)
    duration_ms: Mapped[Optional[float]] = mapped_column(nullable=True)


class ReviewMetrics(Base):
    __tablename__ = "review_metrics"

    review_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), index=True, nullable=False, unique=True)
    repository_size_bytes: Mapped[Optional[int]] = mapped_column(nullable=True)
    files_scanned: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    files_changed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    files_retrieved: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    dependencies_indexed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ast_nodes_parsed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    context_files_selected: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    prompt_size_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    estimated_cost_usd: Mapped[Optional[float]] = mapped_column(nullable=True)
    provider: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    total_duration_ms: Mapped[Optional[float]] = mapped_column(nullable=True)
    stages: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
