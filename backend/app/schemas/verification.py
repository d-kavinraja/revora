import uuid
from typing import Any

from pydantic import BaseModel, Field


class EvidenceSchema(BaseModel):
    evidence_type: str = Field(..., description="Type of evidence e.g. SNIPPET, API_CHECK")
    content: str = Field(..., description="The actual evidence text")
    metadata: dict[str, Any] = Field(default_factory=dict)

class VerificationFindingSchema(BaseModel):
    id: str = Field(..., description="Unique ID for the finding")
    file_path: str = Field(..., description="File path")
    line_number: int | None = Field(None, description="Line number")
    confidence: float = Field(..., description="Confidence score from 0.0 to 1.0")
    severity: str = Field(..., description="Severity level: HIGH, MEDIUM, LOW, CRITICAL")
    issue_type: str = Field(..., description="Issue Type: SECURITY, PERFORMANCE, etc.")
    is_verified: bool = Field(..., description="Whether the finding was successfully verified")
    evidence: list[EvidenceSchema] = Field(default_factory=list, description="List of evidence strings")
    suggestion: list[str] = Field(default_factory=list, description="Suggested fixes")
    checks_passed: list[str] = Field(default_factory=list)
    checks_failed: list[str] = Field(default_factory=list)
    rejection_reason: str | None = Field(None)

class VerificationRequest(BaseModel):
    review_id: uuid.UUID
    repository_url: str
    ai_response_text: str
    changed_files: list[str] = Field(default_factory=list)
    token: str | None = Field(None, description="Optional GitHub token for cloning")

class VerificationMetricsSchema(BaseModel):
    review_id: uuid.UUID
    total_findings: int
    verified_findings: int
    rejected_findings: int
    hallucinations_detected: int
    false_positives_filtered: int
    avg_confidence: float
    verification_duration_ms: int

class HallucinationReportSchema(BaseModel):
    finding_id: str
    hallucination_type: str
    details: str
