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
    suggestion: list[str] = field(default_factory=list)
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
    hallucination_reports: list[dict] = field(default_factory=list)
    false_positive_reports: list[dict] = field(default_factory=list)

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
                    "rejection_reason": f.rejection_reason,
                }
                for f in self.findings
            ],
            "total_findings": self.total_findings,
            "verified_count": self.verified_count,
            "rejected_count": self.rejected_count,
            "avg_confidence": self.avg_confidence,
            "hallucination_reports": self.hallucination_reports,
            "false_positive_reports": self.false_positive_reports,
        }
