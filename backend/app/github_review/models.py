from dataclasses import dataclass, field


@dataclass
class GitHubReviewComment:
    path: str
    body: str
    line: int | None = None
    side: str = "RIGHT"
    suggestion: str | None = None


@dataclass
class GitHubReviewSummary:
    body: str
    event: str = "COMMENT"  # COMMENT, APPROVE, REQUEST_CHANGES
    risk_score: str = "low"  # low, medium, high, critical
    comments: list[GitHubReviewComment] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
