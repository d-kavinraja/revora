from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class GitHubReviewComment:
    path: str
    body: str
    line: Optional[int] = None
    side: str = "RIGHT"
    suggestion: Optional[str] = None


@dataclass
class GitHubReviewSummary:
    body: str
    event: str = "COMMENT"  # COMMENT, APPROVE, REQUEST_CHANGES
    risk_score: str = "low"  # low, medium, high, critical
    comments: List[GitHubReviewComment] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
