from dataclasses import dataclass, field
from typing import Optional


@dataclass
class VerifiedFinding:
    id: str
    file_path: str
    line_number: Optional[int]
    issue_type: str  # bug, security, performance, style, improvement
    severity: str  # critical, high, medium, low
    description: str
    suggestion: Optional[str] = None
    confidence: float = 0.0
    is_verified: bool = False
    checks_passed: list[str] = field(default_factory=list)
    checks_failed: list[str] = field(default_factory=list)
    rejection_reason: Optional[str] = None


@dataclass
class VerificationResult:
    findings: list[VerifiedFinding] = field(default_factory=list)
    total_findings: int = 0
    verified_count: int = 0
    rejected_count: int = 0
    avg_confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "findings": [
                {
                    "id": f.id,
                    "file_path": f.file_path,
                    "line_number": f.line_number,
                    "issue_type": f.issue_type,
                    "severity": f.severity,
                    "description": f.description,
                    "suggestion": f.suggestion,
                    "confidence": f.confidence,
                    "is_verified": f.is_verified,
                    "checks_passed": f.checks_passed,
                    "checks_failed": f.checks_failed,
                }
                for f in self.findings if f.is_verified
            ],
            "total_findings": self.total_findings,
            "verified_count": self.verified_count,
            "rejected_count": self.rejected_count,
            "avg_confidence": self.avg_confidence,
        }
