from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field
import uuid

class EvidenceSchema(BaseModel):
    evidence_type: str = Field(..., description="Type of evidence e.g. SNIPPET, API_CHECK")
    content: str = Field(..., description="The actual evidence text")
    metadata: Dict[str, Any] = Field(default_factory=dict)

class VerificationFindingSchema(BaseModel):
    id: str = Field(..., description="Unique ID for the finding")
    file_path: str = Field(..., description="File path")
    line_number: Optional[int] = Field(None, description="Line number")
    confidence: float = Field(..., description="Confidence score from 0.0 to 1.0")
    severity: str = Field(..., description="Severity level: HIGH, MEDIUM, LOW, CRITICAL")
    issue_type: str = Field(..., description="Issue Type: SECURITY, PERFORMANCE, etc.")
    is_verified: bool = Field(..., description="Whether the finding was successfully verified")
    evidence: List[EvidenceSchema] = Field(default_factory=list, description="List of evidence strings")
    suggestion: List[str] = Field(default_factory=list, description="Suggested fixes")
    checks_passed: List[str] = Field(default_factory=list)
    checks_failed: List[str] = Field(default_factory=list)
    rejection_reason: Optional[str] = Field(None)

class VerificationRequest(BaseModel):
    review_id: uuid.UUID
    repository_url: str
    ai_response_text: str
    changed_files: List[str] = Field(default_factory=list)
    token: Optional[str] = Field(None, description="Optional GitHub token for cloning")

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
