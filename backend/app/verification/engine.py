import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select as sa_select
from sqlalchemy.exc import IntegrityError

from app.db.session import AsyncSessionLocal, get_sqlstate
from app.models.review import Review
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

# Sub-directory used for verification files that can never be persisted
# (malformed JSON, missing parent Review, deterministic integrity errors).
# The startup glob only matches *.json in the parent directory, so quarantined
# files are never replayed as normal pending work.
QUARANTINED_VERIFICATION_DIR_NAME = "errors"

# SQLSTATE classes that are deterministic and can never be fixed by retrying:
# 23xxx = integrity constraint violation (23503 = FK, 23502 = not null,
# 23505 = unique), 22xxx = data exception (invalid value/type/truncation).
_PERMANENT_SQLSTATE_PREFIXES = ("23", "22")


class MissingReviewParentError(Exception):
    """Permanent failure: the parent Review row for verification is absent.

    The existence check that raises this is advisory only; the database FK on
    verification_metrics.review_id remains the final integrity guarantee.
    """


@dataclass(frozen=True)
class PersistenceOutcome:
    """Result of a bounded verification-persistence attempt."""

    persisted: bool
    permanent: bool = False
    missing_review: bool = False
    attempts: int = 0
    error: BaseException | None = None


def _record_persistence_failure() -> int:
    global VERIFICATION_PERSIST_FAILURES
    VERIFICATION_PERSIST_FAILURES += 1
    return VERIFICATION_PERSIST_FAILURES


def _is_permanent_persistence_error(error: BaseException) -> bool:
    """Classify deterministic persistence failures; everything else stays retryable.

    Unknown exceptions deliberately retain the historical bounded-retry
    behavior so a novel transient failure is not silently downgraded.
    """
    if isinstance(error, (MissingReviewParentError, IntegrityError)):
        return True
    state = get_sqlstate(error)
    return bool(state and state.startswith(_PERMANENT_SQLSTATE_PREFIXES))


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
            outcome = await self._persist_with_retry_detailed(
                parsed_uuid, verified_raw, metrics, execution_id=execution_id
            )
            if outcome.persisted:
                await verification_cache.set_verification_result(
                    str(review_id), result.to_dict()
                )
            elif outcome.permanent:
                # A deterministic integrity error (e.g. a missing Review parent)
                # can never be fixed by replaying the same payload. Writing a
                # pending file would create a poison pill that fails on every
                # subsequent startup, so deliberately do not write one.
                logger.error(
                    "Verification results for review %s were NOT persisted "
                    "because of a permanent error (%s attempt(s)); no replayable "
                    "pending file was written. Findings remain available in the "
                    "HTTP response and the GitHub PR review.",
                    review_id,
                    outcome.attempts,
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
        """Boolean compatibility wrapper around the detailed persistence path."""
        outcome = await self._persist_with_retry_detailed(
            review_id,
            verified_findings,
            metrics,
            max_attempts=max_attempts,
            execution_id=execution_id,
        )
        return outcome.persisted

    async def _persist_with_retry_detailed(
        self,
        review_id: uuid.UUID,
        verified_findings: list[dict[str, Any]],
        metrics: dict[str, Any],
        max_attempts: int = 3,
        execution_id: uuid.UUID | None = None,
    ) -> PersistenceOutcome:
        """Bounded retries with exponential backoff for verification persistence.

        Only errors classified as transient are retried. Deterministic database
        integrity errors (foreign-key, not-null, unique, invalid data) and a
        missing parent Review fail immediately: retrying an identical INSERT
        can never succeed, and replaying it as a pending file creates a poison
        pill. The commit inside ``_persist_to_db`` is atomic, so a failed
        attempt leaves no rows behind and a transient retry cannot duplicate.
        """
        import asyncio

        attempts = 0
        for attempt in range(1, max_attempts + 1):
            attempts = attempt
            try:
                await self._persist_to_db(
                    review_id, verified_findings, metrics, execution_id=execution_id
                )
                return PersistenceOutcome(persisted=True, attempts=attempts)
            except Exception as error:
                if _is_permanent_persistence_error(error):
                    total = _record_persistence_failure()
                    missing = isinstance(error, MissingReviewParentError)
                    logger.error(
                        "Verification persistence failed permanently for review %s "
                        "(attempt %d/%d, not retried; missing_parent=%s); "
                        "total persistence failures since startup: %d; %s",
                        review_id,
                        attempt,
                        max_attempts,
                        missing,
                        total,
                        sanitize_error_message(error),
                    )
                    return PersistenceOutcome(
                        persisted=False,
                        permanent=True,
                        missing_review=missing,
                        attempts=attempts,
                        error=error,
                    )
                logger.warning(
                    "Verification persistence failed (attempt %d/%d) for review %s: %s",
                    attempt,
                    max_attempts,
                    review_id,
                    sanitize_error_message(error),
                )
                if attempt < max_attempts:
                    await asyncio.sleep(min(2 ** (attempt - 1) * 0.5, 4.0))
        total = _record_persistence_failure()
        logger.error(
            "Verification persistence exhausted after %d attempts for review %s; "
            "total persistence failures since startup: %d",
            max_attempts,
            review_id,
            total,
        )
        return PersistenceOutcome(persisted=False, attempts=attempts)

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

    def _quarantined_dir(self) -> Path:
        return PENDING_VERIFICATION_DIR / QUARANTINED_VERIFICATION_DIR_NAME

    def _quarantine_pending_file(self, path: Path, reason: str) -> Path | None:
        """Move an unrecoverable pending file out of the retry queue.

        Data is preserved, never silently deleted. A name collision is resolved
        deterministically so an unrelated quarantined file is never overwritten.
        """
        quarantine_dir = self._quarantined_dir()
        try:
            quarantine_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            target = quarantine_dir / path.name
            if target.exists():
                index = 1
                while (quarantine_dir / f"{path.stem}.{index}{path.suffix}").exists():
                    index += 1
                target = quarantine_dir / f"{path.stem}.{index}{path.suffix}"
            os.replace(path, target)
            logger.warning(
                "Quarantined unrecoverable pending verification file %s as %s: %s",
                path.name,
                target.name,
                sanitize_error_message(reason),
            )
            return target
        except Exception as quarantine_error:
            logger.error(
                "Failed to quarantine pending verification file %s: %s",
                path.name,
                sanitize_error_message(quarantine_error),
            )
            return None

    async def recover_pending_files(self) -> dict[str, int]:
        """Best-effort startup recovery: attempt to flush pending files to DB.

        Transient failures keep the file for the next startup. Permanently
        unrecoverable files (missing parent, deterministic integrity error,
        malformed payload) are moved to the quarantine directory so they are
        never replayed. Returns counts of recovered and failed files. Never raises.
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
                # Idempotency. Verification with zero findings persists ONLY a
                # metrics row, so checking verification_results alone would
                # replay an already-successful file forever.
                async with AsyncSessionLocal() as db:
                    existing_result = await db.execute(
                        sa_select(VerificationResultModel.id).where(
                            VerificationResultModel.review_id == review_id
                        ).limit(1)
                    )
                    already_persisted = existing_result.scalars().first() is not None
                    if not already_persisted:
                        existing_metric = await db.execute(
                            sa_select(VerificationMetricModel.id).where(
                                VerificationMetricModel.review_id == review_id
                            ).limit(1)
                        )
                        already_persisted = existing_metric.scalars().first() is not None
                    if already_persisted:
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
                outcome = await self._persist_with_retry_detailed(
                    review_id,
                    data.get("verified_findings", []),
                    data.get("metrics", {}),
                    execution_id=execution_id,
                )
                if outcome.persisted:
                    path.unlink(missing_ok=True)
                    recovered += 1
                    logger.info(
                        "Recovered pending verification for review %s", review_id
                    )
                elif outcome.permanent:
                    self._quarantine_pending_file(
                        path,
                        f"permanent persistence failure for review {review_id}"
                        + (
                            " (parent Review missing)"
                            if outcome.missing_review
                            else ""
                        ),
                    )
                    failed += 1
                else:
                    # Genuinely transient: keep the retryable pending file.
                    failed += 1
            except (json.JSONDecodeError, KeyError, ValueError) as parse_error:
                logger.warning(
                    "Malformed pending verification file %s: %s; quarantining",
                    path.name,
                    sanitize_error_message(parse_error),
                )
                self._quarantine_pending_file(path, "malformed payload")
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
            # Advisory parent check. This is NOT a substitute for the database
            # FK — a concurrent delete can still happen after this read — but
            # it turns the common stale-ID case into a clear, permanent,
            # non-retryable failure instead of an opaque FK violation.
            parent = await db.execute(
                sa_select(Review.id).where(Review.id == review_id).limit(1)
            )
            if parent.scalars().first() is None:
                raise MissingReviewParentError(
                    f"Review {review_id} is not present; verification metrics "
                    "require an existing parent Review row."
                )

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
