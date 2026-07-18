import uuid
from typing import Optional, List, Dict, Any
from sqlalchemy import String, ForeignKey, Integer, Boolean, Float, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, JSON_TYPE

class VerificationResultModel(Base):
    __tablename__ = "verification_results"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    review_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), index=True, nullable=False)
    finding_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    line_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False) # SECURITY, PERFORMANCE, etc.
    severity: Mapped[str] = mapped_column(String(20), nullable=False) # HIGH, MEDIUM, LOW, CRITICAL
    description: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_fix: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Relationships
    evidence: Mapped[List["ReviewEvidenceModel"]] = relationship("ReviewEvidenceModel", back_populates="verification_result", cascade="all, delete-orphan")
    hallucination_report: Mapped[Optional["HallucinationReportModel"]] = relationship("HallucinationReportModel", back_populates="verification_result", uselist=False, cascade="all, delete-orphan")
    false_positive_report: Mapped[Optional["FalsePositiveReportModel"]] = relationship("FalsePositiveReportModel", back_populates="verification_result", uselist=False, cascade="all, delete-orphan")

class ReviewEvidenceModel(Base):
    __tablename__ = "review_evidence"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    verification_result_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("verification_results.id", ondelete="CASCADE"), index=True, nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(50), nullable=False) # SNIPPET, API_CHECK, RULE_MATCH
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(JSON_TYPE, default=dict, server_default='{}')

    # Relationships
    verification_result: Mapped["VerificationResultModel"] = relationship("VerificationResultModel", back_populates="evidence")

class HallucinationReportModel(Base):
    __tablename__ = "hallucination_reports"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    verification_result_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("verification_results.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    hallucination_type: Mapped[str] = mapped_column(String(50), nullable=False) # FAKE_FILE, FAKE_API, INVALID_LINE
    details: Mapped[str] = mapped_column(Text, nullable=False)

    # Relationships
    verification_result: Mapped["VerificationResultModel"] = relationship("VerificationResultModel", back_populates="hallucination_report")

class FalsePositiveReportModel(Base):
    __tablename__ = "false_positive_reports"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    verification_result_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("verification_results.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    reason_category: Mapped[str] = mapped_column(String(50), nullable=False) # DUPLICATE, GENERIC, LOW_CONFIDENCE
    details: Mapped[str] = mapped_column(Text, nullable=False)

    # Relationships
    verification_result: Mapped["VerificationResultModel"] = relationship("VerificationResultModel", back_populates="false_positive_report")

class VerificationMetricModel(Base):
    __tablename__ = "verification_metrics"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    review_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), index=True, nullable=False)
    total_findings: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    verified_findings: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_findings: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hallucinations_detected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    false_positives_filtered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    verification_duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
