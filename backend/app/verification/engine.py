import logging
import uuid
import os
import re
from typing import List, Dict, Any, Optional

from app.verification.pipeline import pipeline
from app.verification.cache import verification_cache
from app.verification.models import VerificationResult, VerifiedFinding
from app.models.verification import (
    VerificationResultModel,
    VerificationMetricModel,
    HallucinationReportModel,
    FalsePositiveReportModel,
    ReviewEvidenceModel
)
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

class VerificationEngine:
    """Verifies AI-generated findings against actual code."""

    async def verify(self, ai_response: str, repo_path: str, changed_files: List[str] = None, context: Dict[str, Any] = None) -> VerificationResult:
        logger.info(f"Starting verification of AI findings")
        
        if context is None:
            context = {}
        context["changed_files"] = changed_files or []
        
        # Populate dependencies for HallucinationDetector
        context["dependencies"] = await self._parse_dependencies(repo_path)
        
        # Extract findings
        raw_findings = self._parse_findings(ai_response)
        
        # Run pipeline
        verified_raw, metrics = await pipeline.process(raw_findings, repo_path, context)
        
        # Convert raw to dataclasses for downstream compatibility
        verified_findings = []
        for finding in verified_raw:
            verified_findings.append(VerifiedFinding(
                id=finding.get("id", str(uuid.uuid4())[:8]),
                file_path=finding.get("file_path", ""),
                line_number=finding.get("line_number"),
                issue_type=finding.get("category", "improvement").lower(),
                severity=finding.get("severity", "medium").lower(),
                description=finding.get("description", ""),
                suggestion=[finding.get("suggested_fix")] if finding.get("suggested_fix") else [],
                confidence=finding.get("confidence", 0.0),
                is_verified=finding.get("verified", False),
                checks_passed=[],
                checks_failed=[],
                rejection_reason=None
            ))
            
        result = VerificationResult(
            findings=verified_findings,
            total_findings=metrics.get("total_findings", 0),
            verified_count=metrics.get("verified_findings", 0),
            rejected_count=metrics.get("rejected_findings", 0),
            avg_confidence=metrics.get("avg_confidence", 0.0),
            hallucination_reports=metrics.get("hallucination_reports", []),
            false_positive_reports=metrics.get("false_positive_reports", [])
        )
        
        review_id = context.get("review_id")
        if review_id:
            # Cache results
            await verification_cache.set_verification_result(str(review_id), result.to_dict())
            
            # Persist to database
            try:
                parsed_uuid = uuid.UUID(review_id) if isinstance(review_id, str) else review_id
                await self._persist_to_db(parsed_uuid, verified_raw, metrics)
            except Exception as e:
                logger.error(f"Failed to persist verification results to DB: {e}")
                
        logger.info(f"Verification complete: {result.verified_count} verified, {result.rejected_count} rejected")
        return result

    async def _persist_to_db(self, review_id: uuid.UUID, verified_findings: List[Dict[str, Any]], metrics: Dict[str, Any]):
        async with AsyncSessionLocal() as db:
            # Save metrics
            db_metric = VerificationMetricModel(
                review_id=review_id,
                total_findings=metrics.get("total_findings", 0),
                verified_findings=metrics.get("verified_findings", 0),
                rejected_findings=metrics.get("rejected_findings", 0),
                hallucinations_detected=metrics.get("hallucinations_detected", 0),
                false_positives_filtered=metrics.get("false_positives_filtered", 0),
                avg_confidence=metrics.get("avg_confidence", 0.0),
                verification_duration_ms=metrics.get("verification_duration_ms", 0)
            )
            db.add(db_metric)
            
            # Save verified findings
            for finding in verified_findings:
                db_finding = VerificationResultModel(
                    review_id=review_id,
                    finding_id=finding.get("id", str(uuid.uuid4())),
                    file_path=finding.get("file_path", ""),
                    line_number=finding.get("line_number"),
                    category=finding.get("category", "IMPROVEMENT"),
                    severity=finding.get("severity", "MEDIUM"),
                    description=finding.get("description", ""),
                    suggested_fix=finding.get("suggested_fix") if finding.get("suggested_fix") else None,
                    is_verified=True,
                    confidence_score=finding.get("confidence", 0.0),
                )
                db.add(db_finding)
                
                # Save evidence
                for ev in finding.get("evidence", []):
                    db.add(ReviewEvidenceModel(
                        verification_result=db_finding,
                        evidence_type=ev.get("evidence_type", "SNIPPET"),
                        content=ev.get("content", ""),
                        metadata_json=ev.get("metadata", {})
                    ))
            
            # Save hallucinations
            for h in metrics.get("hallucination_reports", []):
                raw = h.get("finding", {})
                # Create a rejected finding record first
                db_finding = VerificationResultModel(
                    review_id=review_id,
                    finding_id=h.get("finding_id", str(uuid.uuid4())),
                    file_path=raw.get("file_path", "unknown"),
                    line_number=raw.get("line_number"),
                    category=raw.get("category", "UNKNOWN"),
                    severity=raw.get("severity", "UNKNOWN"),
                    description=raw.get("description", "Rejected finding"),
                    is_verified=False,
                    rejection_reason="Hallucination"
                )
                db.add(db_finding)
                db.add(HallucinationReportModel(
                    verification_result=db_finding,
                    hallucination_type=h.get("type", "UNKNOWN"),
                    details=h.get("details", "")
                ))
                
            # Save false positives
            for fp in metrics.get("false_positive_reports", []):
                raw = fp.get("finding", {})
                db_finding = VerificationResultModel(
                    review_id=review_id,
                    finding_id=fp.get("finding_id", str(uuid.uuid4())),
                    file_path=raw.get("file_path", "unknown"),
                    line_number=raw.get("line_number"),
                    category=raw.get("category", "UNKNOWN"),
                    severity=raw.get("severity", "UNKNOWN"),
                    description=raw.get("description", "Rejected finding"),
                    is_verified=False,
                    rejection_reason="False Positive"
                )
                db.add(db_finding)
                db.add(FalsePositiveReportModel(
                    verification_result=db_finding,
                    reason_category=fp.get("reason_category", "UNKNOWN"),
                    details=fp.get("details", "")
                ))

            await db.commit()

    async def _parse_dependencies(self, repo_path: str) -> List[str]:
        """Simple dependency parsing to populate context for HallucinationDetector."""
        deps = set()
        req_path = os.path.join(repo_path, "requirements.txt")
        pkg_path = os.path.join(repo_path, "package.json")
        
        import asyncio
        req_exists = await asyncio.to_thread(os.path.exists, req_path)
        if req_exists:
            try:
                import aiofiles
                async with aiofiles.open(req_path, mode="r", encoding="utf-8") as f:
                    lines = await f.readlines()
                    for line in lines:
                        line = line.split("==")[0].strip()
                        if line and not line.startswith("#"):
                            deps.add(line.lower())
            except Exception:
                pass
                
        pkg_exists = await asyncio.to_thread(os.path.exists, pkg_path)
        if pkg_exists:
            try:
                import aiofiles
                import json
                async with aiofiles.open(pkg_path, mode="r", encoding="utf-8") as f:
                    content = await f.read()
                    data = json.loads(content)
                    deps.update(data.get("dependencies", {}).keys())
                    deps.update(data.get("devDependencies", {}).keys())
            except Exception:
                pass
                
        return list(deps)

    def _parse_findings(self, response: str) -> List[Dict[str, Any]]:
        """
        Mock implementation of the Review Parser.
        """
        findings = []
        sections = re.split(r"###\s+", response)

        for section in sections:
            if not section.strip():
                continue

            category = "IMPROVEMENT"
            if "security" in section.lower():
                category = "SECURITY"
            elif "bug" in section.lower():
                category = "BUG"
            elif "performance" in section.lower():
                category = "PERFORMANCE"

            blocks = re.split(r"\n(?:\*\*|\d+\.)\s+", section)
            for block in blocks:
                if not block.strip() or len(block.strip()) < 20:
                    continue

                # Broaden regex for multiple languages
                file_match = re.search(r"`([^`]+\.(?:py|js|ts|tsx|jsx|go|java|rs|rb|php|swift|kt|scala|c|cpp|h|hpp|sh|yaml|yml|json|tf|sql))`", block)
                line_match = re.search(r"line\s+(\d+)", block, re.IGNORECASE)
                severity_match = re.search(r"(critical|high|medium|low)", block, re.IGNORECASE)
                
                # Extract suggested fix
                suggested_fix = ""
                sug_match = re.search(r"(?:Suggestion|Fix|Suggested Fix):\s*(.*)", block, re.IGNORECASE | re.DOTALL)
                if sug_match:
                    suggested_fix = sug_match.group(1).strip()

                if file_match:
                    findings.append({
                        "id": str(uuid.uuid4())[:8],
                        "file_path": file_match.group(1),
                        "line_number": int(line_match.group(1)) if line_match else None,
                        "category": category,
                        "severity": severity_match.group(1).upper() if severity_match else "MEDIUM",
                        "description": block.strip()[:500],
                        "suggested_fix": suggested_fix
                    })

        return findings

verification_engine = VerificationEngine()
