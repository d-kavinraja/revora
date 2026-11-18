import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any

from app.db.session import AsyncSessionLocal
from app.models.verification import (
    FalsePositiveReportModel,
    HallucinationReportModel,
    ReviewEvidenceModel,
    VerificationMetricModel,
    VerificationResultModel,
)
from app.security.error_sanitizer import sanitize_error_message
from app.verification.cache import verification_cache
from app.verification.models import VerificationResult, VerifiedFinding
from app.verification.pipeline import pipeline

logger = logging.getLogger(__name__)

# Count of verification persistence failures since process startup.
# Exposed in logs on each final failure; restart resets it.
VERIFICATION_PERSIST_FAILURES = 0

# Best-effort pending verification results directory.  Files here are written
# when all DB persistence attempts fail.  They are NOT durable (ephemeral on
# Render free tier) and are never exposed via any API endpoint.
PENDING_VERIFICATION_DIR = Path(os.environ.get("TMPDIR", "/tmp")) / "revora_pending_verification"


class VerificationEngine:
    """Verifies AI-generated findings against actual code."""

    async def verify(
        self,
        ai_response: str,
        repo_path: str,
        changed_files: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> VerificationResult:
        logger.info("Starting verification of AI findings")

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
            verified_findings.append(
                VerifiedFinding(
                    id=finding.get("id", str(uuid.uuid4())[:8]),
                    title=finding.get("title", ""),
                    file_path=finding.get("file_path", ""),
                    line_number=finding.get("line_number"),
                    issue_type=finding.get("category", "improvement").lower(),
                    severity=finding.get("severity", "medium").lower(),
                    description=finding.get("description", ""),
                    suggestion=(
                        [finding.get("suggested_fix")]
                        if finding.get("suggested_fix")
                        else []
                    ),
                    confidence=finding.get("confidence", 0.0),
                    is_verified=finding.get("verified", False),
                    checks_passed=[],
                    checks_failed=[],
                    rejection_reason=None,
                )
            )

        result = VerificationResult(
            findings=verified_findings,
            total_findings=metrics.get("total_findings", 0),
            verified_count=metrics.get("verified_findings", 0),
            rejected_count=metrics.get("rejected_findings", 0),
            avg_confidence=metrics.get("avg_confidence", 0.0),
            hallucination_reports=metrics.get("hallucination_reports", []),
            false_positive_reports=metrics.get("false_positive_reports", []),
        )

        review_id = context.get("review_id")
        execution_id = context.get("execution_id")
        if isinstance(execution_id, str):
            try:
                execution_id = uuid.UUID(execution_id)
            except ValueError:
                execution_id = None

        if review_id:
            # Persist FIRST, expose through the cache second. A verification
            # result must never be readable (cache hit) while its database
            # rows are missing because persistence failed.
            parsed_uuid = (
                uuid.UUID(review_id) if isinstance(review_id, str) else review_id
            )
            persisted = await self._persist_with_retry(
                parsed_uuid, verified_raw, metrics, execution_id=execution_id
            )
            if persisted:
                await verification_cache.set_verification_result(
                    str(review_id), result.to_dict()
                )
            else:
                # Best-effort: write to a local pending file.  This is NOT
                # durable (ephemeral disk on Render free tier) and does NOT
                # guarantee recovery.  It is an attempt, not a promise.
                self._write_pending_file(
                    parsed_uuid, verified_raw, metrics, execution_id=execution_id
                )
                logger.error(
                    "Verification results could not be persisted for review %s "
                    "after retries; result was NOT cached. A best-effort pending "
                    "file was written (ephemeral, not durable). Findings remain "
                    "available in the HTTP response and the GitHub PR review.",
                    review_id,
                )

        logger.info(
            f"Verification complete: {result.verified_count} verified, {result.rejected_count} rejected"
        )
        return result

    async def _persist_with_retry(
        self,
        review_id: uuid.UUID,
        verified_findings: list[dict[str, Any]],
        metrics: dict[str, Any],
        max_attempts: int = 3,
        execution_id: uuid.UUID | None = None,
    ) -> bool:
        """Bounded retries with exponential backoff for verification persistence.

        The commit inside ``_persist_to_db`` is atomic, so a failed attempt
        leaves no rows behind and a retry cannot create duplicates.
        """
        import asyncio

        for attempt in range(1, max_attempts + 1):
            try:
                await self._persist_to_db(
                    review_id, verified_findings, metrics, execution_id=execution_id
                )
                return True
            except Exception as error:
                logger.warning(
                    "Verification persistence failed (attempt %d/%d) for review %s: %s",
                    attempt,
                    max_attempts,
                    review_id,
                    sanitize_error_message(error),
                )
                if attempt < max_attempts:
                    await asyncio.sleep(min(2 ** (attempt - 1) * 0.5, 4.0))
        global VERIFICATION_PERSIST_FAILURES
        VERIFICATION_PERSIST_FAILURES += 1
        logger.error(
            "Verification persistence exhausted after %d attempts for review %s; "
            "total persistence failures since startup: %d",
            max_attempts,
            review_id,
            VERIFICATION_PERSIST_FAILURES,
        )
        return False

    def _pending_file_path(self, review_id: uuid.UUID) -> Path:
        return PENDING_VERIFICATION_DIR / f"{review_id}.json"

    def _write_pending_file(
        self,
        review_id: uuid.UUID,
        verified_findings: list[dict[str, Any]],
        metrics: dict[str, Any],
        execution_id: uuid.UUID | None = None,
    ) -> None:
        """Best-effort: write verification data to a local file when DB is
        unavailable.  The file is NOT durably persisted (ephemeral disk).
        Contains only finding metadata and metrics — no raw AI response,
        no credentials, no user data."""
        try:
            PENDING_VERIFICATION_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(PENDING_VERIFICATION_DIR, 0o700)
            data = {
                "review_id": str(review_id),
                "execution_id": str(execution_id) if execution_id else None,
                "verified_findings": verified_findings,
                "metrics": metrics,
                "timestamp": __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat(),
            }
            target = self._pending_file_path(review_id)
            tmp = target.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target)
            try:
                os.chmod(target, 0o600)
            except OSError:
                pass
            logger.warning(
                "Wrote best-effort pending verification file for review %s "
                "(NOT durably persisted — ephemeral disk)",
                review_id,
            )
        except Exception as write_error:
            logger.error(
                "Failed to write pending verification file for review %s: %s",
                review_id,
                sanitize_error_message(write_error),
            )

    async def recover_pending_files(self) -> dict[str, int]:
        """Best-effort startup recovery: attempt to flush pending files to DB.

        Returns counts of recovered and failed files.  Never raises.
        """
        recovered = 0
        failed = 0
        if not PENDING_VERIFICATION_DIR.exists():
            return {"recovered": recovered, "failed": failed}
        for path in sorted(PENDING_VERIFICATION_DIR.glob("*.json")):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                review_id = uuid.UUID(data["review_id"])
                # Idempotency: check if already persisted
                async with AsyncSessionLocal() as db:
                    from sqlalchemy import select as sa_select
                    from app.models.verification import VerificationResultModel

                    existing = await db.execute(
                        sa_select(VerificationResultModel.id).where(
                            VerificationResultModel.review_id == review_id
                        ).limit(1)
                    )
                    if existing.scalars().first() is not None:
                        path.unlink(missing_ok=True)
                        recovered += 1
                        continue
                # Attempt persistence
                stored_exec_id = data.get("execution_id")
                execution_id = None
                if stored_exec_id:
                    try:
                        execution_id = uuid.UUID(str(stored_exec_id))
                    except ValueError:
                        execution_id = None
                persisted = await self._persist_with_retry(
                    review_id,
                    data.get("verified_findings", []),
                    data.get("metrics", {}),
                    execution_id=execution_id,
                )
                if persisted:
                    path.unlink(missing_ok=True)
                    recovered += 1
                    logger.info(
                        "Recovered pending verification for review %s", review_id
                    )
                else:
                    failed += 1
            except (json.JSONDecodeError, KeyError, ValueError) as parse_error:
                logger.warning(
                    "Malformed pending verification file %s: %s; moving to error dir",
                    path.name,
                    sanitize_error_message(parse_error),
                )
                error_dir = PENDING_VERIFICATION_DIR / "errors"
                error_dir.mkdir(mode=0o700, exist_ok=True)
                try:
                    os.replace(path, error_dir / path.name)
                except Exception:
                    pass
                failed += 1
            except Exception as error:
                logger.error(
                    "Recovery failed for pending file %s: %s",
                    path.name,
                    sanitize_error_message(error),
                )
                failed += 1
        return {"recovered": recovered, "failed": failed}

    async def _persist_to_db(
        self,
        review_id: uuid.UUID,
        verified_findings: list[dict[str, Any]],
        metrics: dict[str, Any],
        execution_id: uuid.UUID | None = None,
    ):
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
                verification_duration_ms=metrics.get("verification_duration_ms", 0),
            )
            db.add(db_metric)

            # Save verified findings
            for finding in verified_findings:
                db_finding = VerificationResultModel(
                    review_id=review_id,
                    execution_id=execution_id,
                    finding_id=finding.get("id", str(uuid.uuid4())),
                    title=finding.get("title", ""),
                    file_path=finding.get("file_path", ""),
                    line_number=finding.get("line_number"),
                    category=finding.get("category", "IMPROVEMENT"),
                    severity=finding.get("severity", "MEDIUM"),
                    description=finding.get("description", ""),
                    suggested_fix=(
                        finding.get("suggested_fix")
                        if finding.get("suggested_fix")
                        else None
                    ),
                    is_verified=True,
                    confidence_score=finding.get("confidence", 0.0),
                )
                db.add(db_finding)

                # Save evidence
                for ev in finding.get("evidence", []):
                    db.add(
                        ReviewEvidenceModel(
                            verification_result=db_finding,
                            evidence_type=ev.get("evidence_type", "SNIPPET"),
                            content=ev.get("content", ""),
                            metadata_json=ev.get("metadata", {}),
                        )
                    )

            # Save hallucinations
            for h in metrics.get("hallucination_reports", []):
                raw = h.get("finding", {})
                # Create a rejected finding record first
                db_finding = VerificationResultModel(
                    review_id=review_id,
                    execution_id=execution_id,
                    finding_id=h.get("finding_id", str(uuid.uuid4())),
                    file_path=raw.get("file_path", "unknown"),
                    line_number=raw.get("line_number"),
                    category=raw.get("category", "UNKNOWN"),
                    severity=raw.get("severity", "UNKNOWN"),
                    description=raw.get("description", "Rejected finding"),
                    is_verified=False,
                    rejection_reason="Hallucination",
                )
                db.add(db_finding)
                db.add(
                    HallucinationReportModel(
                        verification_result=db_finding,
                        hallucination_type=h.get("type", "UNKNOWN"),
                        details=h.get("details", ""),
                    )
                )

            # Save false positives
            for fp in metrics.get("false_positive_reports", []):
                raw = fp.get("finding", {})
                db_finding = VerificationResultModel(
                    review_id=review_id,
                    execution_id=execution_id,
                    finding_id=fp.get("finding_id", str(uuid.uuid4())),
                    file_path=raw.get("file_path", "unknown"),
                    line_number=raw.get("line_number"),
                    category=raw.get("category", "UNKNOWN"),
                    severity=raw.get("severity", "UNKNOWN"),
                    description=raw.get("description", "Rejected finding"),
                    is_verified=False,
                    rejection_reason="False Positive",
                )
                db.add(db_finding)
                db.add(
                    FalsePositiveReportModel(
                        verification_result=db_finding,
                        reason_category=fp.get("reason_category", "UNKNOWN"),
                        details=fp.get("details", ""),
                    )
                )

            await db.commit()

    async def _parse_dependencies(self, repo_path: str) -> list[str]:
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
                import json

                import aiofiles

                async with aiofiles.open(pkg_path, mode="r", encoding="utf-8") as f:
                    content = await f.read()
                    data = json.loads(content)
                    deps.update(data.get("dependencies", {}).keys())
                    deps.update(data.get("devDependencies", {}).keys())
            except Exception:
                pass

        return list(deps)

    def _parse_findings(self, response: str) -> list[dict[str, Any]]:
        """
        Robust implementation of the Review Parser.
        Extracts findings from LLM response, handling JSON formats.
        """
        import json

        findings = []

        # Try to parse as JSON first
        try:
            # Find the JSON block if it's wrapped in markdown or conversational text
            json_str = response

            # Robustly extract the outermost JSON object or array
            first_curly = response.find("{")
            last_curly = response.rfind("}")
            first_square = response.find("[")
            last_square = response.rfind("]")

            is_obj = first_curly != -1 and last_curly != -1
            is_arr = first_square != -1 and last_square != -1

            if is_obj and is_arr:
                if first_curly < first_square and last_curly > last_square:
                    json_str = response[first_curly : last_curly + 1]
                else:
                    json_str = response[first_square : last_square + 1]
            elif is_obj:
                json_str = response[first_curly : last_curly + 1]
            elif is_arr:
                json_str = response[first_square : last_square + 1]

            data = json.loads(json_str)

            # Expecting either a list of findings or an object with a "findings" key
            raw_findings = (
                data.get("findings", [])
                if isinstance(data, dict)
                else data if isinstance(data, list) else []
            )

            for item in raw_findings:
                if not isinstance(item, dict):
                    continue
                findings.append(
                    {
                        "id": str(uuid.uuid4())[:8],
                        "title": item.get("title", ""),
                        "file_path": item.get("file_path", ""),
                        "line_number": item.get("line_number"),
                        "category": item.get("category", "IMPROVEMENT").upper(),
                        "severity": item.get("severity", "MEDIUM").upper(),
                        "description": item.get("description", ""),
                        "suggested_fix": item.get("suggested_fix", ""),
                    }
                )

            if findings:
                return findings
        except json.JSONDecodeError as e:
            logger.warning(
                f"Failed to parse LLM response as JSON: {e}. Falling back to regex."
            )

        # Fallback regex parsing
        sections = re.split(r"###\s+", response) if "###" in response else [response]

        for section in sections:
            if not section.strip():
                continue

            category = "IMPROVEMENT"
            section_lower = section.lower()
            if "security" in section_lower:
                category = "SECURITY"
            elif (
                "bug" in section_lower
                or "error" in section_lower
                or "issue" in section_lower
            ):
                category = "BUG"
            elif "performance" in section_lower:
                category = "PERFORMANCE"

            if "summary" in section_lower and len(section_lower.split()) < 200:
                continue

            blocks = re.split(r"\n\s*(?:\d+\.|\*|-|\*\*|•)\s+", "\n" + section)
            for block in blocks:
                block = block.strip()
                if not block or len(block) < 10:
                    continue

                file_match = re.search(
                    r"`?([a-zA-Z0-9_\-\./\\]+\.(?:py|js|ts|tsx|jsx|go|java|rs|rb|php|swift|kt|scala|c|cpp|h|hpp|sh|yaml|yml|json|tf|sql|md|txt|cfg|ini|toml|env))`?",
                    block,
                )
                line_match = re.search(r"line\s*:?\s*(\d+)", block, re.IGNORECASE)
                severity_match = re.search(
                    r"(critical|high|medium|low)", block, re.IGNORECASE
                )

                suggested_fix = ""
                sug_match = re.search(
                    r"(?:Suggestion|Fix|Suggested Fix|Recommendation):\s*(.*)",
                    block,
                    re.IGNORECASE | re.DOTALL,
                )
                if sug_match:
                    suggested_fix = sug_match.group(1).strip()

                title_match = re.search(r"^\*\*(.*?)\*\*", block) or re.search(
                    r"^([^\.\n]+)", block
                )
                title = title_match.group(1).strip() if title_match else "Finding"

                # Create finding even without file match if description is substantial
                if len(block) >= 20:
                    findings.append(
                        {
                            "id": str(uuid.uuid4())[:8],
                            "title": title[:255],
                            "file_path": file_match.group(1) if file_match else "",
                            "line_number": (
                                int(line_match.group(1)) if line_match else None
                            ),
                            "category": category,
                            "severity": (
                                severity_match.group(1).upper()
                                if severity_match
                                else "MEDIUM"
                            ),
                            "description": block,
                            "suggested_fix": suggested_fix,
                        }
                    )

        # Return empty list if all parsing fails
        return findings


verification_engine = VerificationEngine()
