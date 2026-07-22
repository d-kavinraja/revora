import time
import uuid
from typing import List, Dict, Any, Tuple
import logging

from app.verification.validators import (
    RepositoryValidator,
    SecurityValidator,
    PerformanceValidator,
    ArchitectureValidator,
    RuleValidator,
)
from app.verification.hallucination import HallucinationDetector
from app.verification.confidence import ConfidenceEngine
from app.verification.evidence import EvidenceEngine

logger = logging.getLogger(__name__)

class VerificationPipeline:
    def __init__(self):
        self.validators = [
            RepositoryValidator(),
            SecurityValidator(),
            PerformanceValidator(),
            ArchitectureValidator(),
            RuleValidator()
        ]
        self.hallucination_detector = HallucinationDetector()
        self.confidence_engine = ConfidenceEngine()
        self.evidence_engine = EvidenceEngine()

    async def process(self, findings: List[Dict[str, Any]], repo_path: str, context: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        start_time = time.time()
        
        verified_findings = []
        metrics = {
            "total_findings": len(findings),
            "verified_findings": 0,
            "rejected_findings": 0,
            "hallucinations_detected": 0,
            "false_positives_filtered": 0,
            "avg_confidence": 0.0,
            "verification_duration_ms": 0,
            "hallucination_reports": [],
            "false_positive_reports": []
        }
        
        total_confidence = 0.0
        
        # Deduplication
        unique_findings = []
        seen = set()
        for finding in findings:
            key = (finding.get("file_path"), finding.get("line_number"), finding.get("category"))
            if key in seen:
                metrics["false_positives_filtered"] += 1
                metrics["rejected_findings"] += 1
                finding_id = finding.get("id", str(uuid.uuid4()))
                metrics["false_positive_reports"].append({
                    "finding_id": finding_id,
                    "finding": finding,
                    "reason_category": "DUPLICATE",
                    "details": f"Duplicate finding for {key[2]} at {key[0]}:{key[1]}"
                })
                continue
            seen.add(key)
            unique_findings.append(finding)
        
        for finding in unique_findings:
            # 1. Hallucination Check
            hallucination = self.hallucination_detector.detect(finding, repo_path, context)
            if hallucination:
                metrics["hallucinations_detected"] += 1
                metrics["rejected_findings"] += 1
                finding_id = finding.get("id", str(uuid.uuid4()))
                metrics["hallucination_reports"].append({
                    "finding_id": finding_id,
                    "finding": finding,
                    **hallucination
                })
                continue
                
            # 2. Validation
            validation_results = []
            for validator in self.validators:
                result = await validator.validate(finding, repo_path, context)
                validation_results.append(result)
                
            # 3. Confidence Scoring
            confidence_score = self.confidence_engine.calculate(finding, validation_results)
            finding["confidence"] = confidence_score 
            
            status = self.confidence_engine.get_status(confidence_score)
            
            # 4. False Positive Filtering
            # Only reject clearly low-confidence findings
            if status == "REJECT":
                metrics["false_positives_filtered"] += 1
                metrics["rejected_findings"] += 1
                finding_id = finding.get("id", str(uuid.uuid4()))
                metrics["false_positive_reports"].append({
                    "finding_id": finding_id,
                    "finding": finding,
                    "reason_category": "LOW_CONFIDENCE",
                    "details": f"Finding confidence score {confidence_score:.2f} is below threshold."
                })
                continue
                
            # 5. Evidence Generation (best-effort, not a hard gate)
            evidence = await self.evidence_engine.generate(finding, repo_path)
            if evidence:
                finding["evidence"] = [evidence]
                
            finding["verified"] = True
            verified_findings.append(finding)
            metrics["verified_findings"] += 1
            total_confidence += finding["confidence"]
            
        if verified_findings:
            metrics["avg_confidence"] = total_confidence / len(verified_findings)
            
        metrics["verification_duration_ms"] = int((time.time() - start_time) * 1000)
        
        return verified_findings, metrics

pipeline = VerificationPipeline()
