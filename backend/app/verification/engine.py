import os
import re
import logging
import uuid
from typing import Optional, List

from app.verification.models import VerifiedFinding, VerificationResult

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.5


class VerificationEngine:
    """Verifies AI-generated findings against actual code."""

    async def verify(self, ai_response: str, repo_path: str, changed_files: list[str] = None) -> VerificationResult:
        logger.info("Starting verification of AI findings")
        findings = self._parse_findings(ai_response)
        result = VerificationResult(total_findings=len(findings))

        verified = []
        for finding in findings:
            v = self._verify_finding(finding, repo_path, changed_files or [])
            if v.is_verified and v.confidence >= CONFIDENCE_THRESHOLD:
                verified.append(v)
                result.verified_count += 1
            else:
                result.rejected_count += 1

        result.findings = verified
        result.avg_confidence = sum(f.confidence for f in verified) / len(verified) if verified else 0.0

        logger.info(f"Verification complete: {result.verified_count} verified, {result.rejected_count} rejected")
        return result

    def _parse_findings(self, response: str) -> List[VerifiedFinding]:
        findings = []
        sections = re.split(r"###\s+", response)

        for section in sections:
            if not section.strip():
                continue

            issue_type = "improvement"
            if "security" in section.lower():
                issue_type = "security"
            elif "bug" in section.lower():
                issue_type = "bug"
            elif "performance" in section.lower():
                issue_type = "performance"

            blocks = re.split(r"\n(?:\*\*|\d+\.)\s+", section)
            for block in blocks:
                if not block.strip() or len(block.strip()) < 20:
                    continue

                file_match = re.search(r"`([^`]+\.(?:py|js|ts|tsx|jsx|go|java|rs))`", block)
                line_match = re.search(r"line\s+(\d+)", block, re.IGNORECASE)
                severity_match = re.search(r"(critical|high|medium|low)", block, re.IGNORECASE)

                if file_match:
                    findings.append(VerifiedFinding(
                        id=str(uuid.uuid4())[:8],
                        file_path=file_match.group(1),
                        line_number=int(line_match.group(1)) if line_match else None,
                        issue_type=issue_type,
                        severity=severity_match.group(1).lower() if severity_match else "medium",
                        description=block.strip()[:500],
                    ))

        return findings

    def _verify_finding(self, finding: VerifiedFinding, repo_path: str, changed_files: list[str]) -> VerifiedFinding:
        checks_passed = []
        checks_failed = []

        # Check 1: File exists
        full_path = os.path.join(repo_path, finding.file_path)
        if os.path.exists(full_path):
            finding.checks_passed.append("file_exists")
            checks_passed.append("file_exists")
        else:
            finding.checks_failed.append("file_not_found")
            checks_failed.append("file_not_found")
            finding.confidence = max(0.0, finding.confidence - 0.3)

        # Check 2: File is in changed files
        if finding.file_path in changed_files:
            finding.checks_passed.append("in_changed_files")
            checks_passed.append("in_changed_files")
            finding.confidence += 0.2
        else:
            finding.checks_passed.append("related_file")
            finding.confidence += 0.1

        # Check 3: Line exists in file
        if finding.line_number and os.path.exists(full_path):
            try:
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                if 0 < finding.line_number <= len(lines):
                    finding.checks_passed.append("line_exists")
                    checks_passed.append("line_exists")
                    finding.confidence += 0.2
                else:
                    finding.checks_failed.append("line_not_found")
                    checks_failed.append("line_not_found")
                    finding.confidence = max(0.0, finding.confidence - 0.2)
            except OSError:
                pass

        # Check 4: Description is specific (not too generic)
        generic_phrases = ["might be", "could potentially", "consider", "you may want to", "it is recommended"]
        is_generic = any(phrase in finding.description.lower() for phrase in generic_phrases)
        if not is_generic:
            finding.checks_passed.append("specific_description")
            finding.confidence += 0.1
        else:
            finding.confidence = max(0.0, finding.confidence - 0.1)

        # Base confidence
        finding.confidence = max(0.1, min(1.0, finding.confidence + 0.3))

        # Final determination
        if len(checks_failed) > len(checks_passed):
            finding.rejection_reason = f"Failed checks: {', '.join(checks_failed)}"
            finding.is_verified = False
        elif finding.confidence >= CONFIDENCE_THRESHOLD:
            finding.is_verified = True
        else:
            finding.rejection_reason = f"Confidence {finding.confidence:.2f} below threshold {CONFIDENCE_THRESHOLD}"
            finding.is_verified = False

        return finding


verification_engine = VerificationEngine()
