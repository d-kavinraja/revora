import time
import hashlib
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RetrievedContext:
    file_path: str
    content: str
    relevance_score: float
    source: str
    metadata: dict = field(default_factory=dict)
    compressed: bool = False
    original_tokens: int = 0
    rank_position: int = 999

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "content": self.content[:500],
            "relevance_score": self.relevance_score,
            "source": self.source,
            "metadata": self.metadata,
            "compressed": self.compressed,
            "original_tokens": self.original_tokens,
        }

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode()).hexdigest()[:16]


@dataclass
class RetrievalResult:
    changed_files: list[RetrievedContext] = field(default_factory=list)
    related_files: list[RetrievedContext] = field(default_factory=list)
    test_files: list[RetrievedContext] = field(default_factory=list)
    config_files: list[RetrievedContext] = field(default_factory=list)
    api_endpoints: list[RetrievedContext] = field(default_factory=list)
    db_schemas: list[RetrievedContext] = field(default_factory=list)
    security_context: list[RetrievedContext] = field(default_factory=list)
    impact_context: list[RetrievedContext] = field(default_factory=list)
    historical_context: list[RetrievedContext] = field(default_factory=list)
    rule_context: list[RetrievedContext] = field(default_factory=list)
    documentation_context: list[RetrievedContext] = field(default_factory=list)
    total_tokens: int = 0
    budget_used: float = 0.0
    budget_limit: int = 10000
    retrieval_time_ms: float = 0.0
    cache_hit: bool = False
    fallback_used: Optional[str] = None

    def all_contexts(self) -> list[RetrievedContext]:
        return (
            self.changed_files
            + self.related_files
            + self.test_files
            + self.config_files
            + self.api_endpoints
            + self.db_schemas
            + self.security_context
            + self.impact_context
            + self.historical_context
            + self.rule_context
            + self.documentation_context
        )

    def to_dict(self) -> dict:
        return {
            "changed_files": [c.to_dict() for c in self.changed_files],
            "related_files": [c.to_dict() for c in self.related_files],
            "test_files": [c.to_dict() for c in self.test_files],
            "config_files": [c.to_dict() for c in self.config_files],
            "total_tokens": self.total_tokens,
            "budget_used": self.budget_used,
            "budget_limit": self.budget_limit,
            "retrieval_time_ms": self.retrieval_time_ms,
            "cache_hit": self.cache_hit,
            "fallback_used": self.fallback_used,
        }


@dataclass
class RetrievalConfig:
    budget: int = 10000
    max_related_files: int = 15
    max_test_files: int = 5
    max_depth: int = 2
    enable_ranking: bool = True
    enable_compression: bool = True
    enable_cache: bool = True
    enable_fallback: bool = True
    enable_graph_traversal: bool = True
    enable_security_context: bool = True
    enable_impact_analysis: bool = True
    enable_historical_context: bool = False
    enable_documentation: bool = True
    enable_similar_code: bool = False
    cache_ttl_seconds: int = 300
    fallback_strategy: str = "graceful"
