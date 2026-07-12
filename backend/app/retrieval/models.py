from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RetrievedContext:
    file_path: str
    content: str
    relevance_score: float
    source: str  # import_graph, call_graph, test, related, config
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "content": self.content[:500],  # Truncate for serialization
            "relevance_score": self.relevance_score,
            "source": self.source,
            "metadata": self.metadata,
        }


@dataclass
class RetrievalResult:
    changed_files: list[RetrievedContext] = field(default_factory=list)
    related_files: list[RetrievedContext] = field(default_factory=list)
    test_files: list[RetrievedContext] = field(default_factory=list)
    config_files: list[RetrievedContext] = field(default_factory=list)
    total_tokens: int = 0
    budget_used: float = 0.0

    def to_dict(self) -> dict:
        return {
            "changed_files": [c.to_dict() for c in self.changed_files],
            "related_files": [c.to_dict() for c in self.related_files],
            "test_files": [c.to_dict() for c in self.test_files],
            "config_files": [c.to_dict() for c in self.config_files],
            "total_tokens": self.total_tokens,
            "budget_used": self.budget_used,
        }
