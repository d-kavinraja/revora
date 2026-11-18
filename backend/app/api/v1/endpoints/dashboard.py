import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.github import Installation, PullRequest, Repository
from app.models.review import Review
from app.models.user import User
from app.models.verification import VerificationResultModel

logger = logging.getLogger(__name__)

router = APIRouter()

_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _normalize_severity(value: str | None) -> str:
    return (value or "medium").strip().lower()


def _finding_fingerprint(
    review_id,
    file_path: str | None,
    line_number: int | None,
    category: str | None,
    description: str | None,
) -> tuple:
    """Stable deduplication key for a finding.

    Reruns of the same review re-detect the same issue; the rows are appended
    to verification_results with a fresh finding_id. A (review, location,
    category) fingerprint collapses those reruns without merging distinct
    findings from the same review. Findings without a file path fall back to
    (review, category, normalized description) so they cannot merge with
    location-based findings.
    """
    fp = (file_path or "").strip().lower()
    cat = (category or "").strip().upper()
    if fp:
        return (
            "loc",
            str(review_id),
            fp,
            line_number if line_number is not None else -1,
            cat,
        )
    return (
        "desc",
        str(review_id),
        cat,
        (description or "").strip().lower(),
    )


@router.get("/stats", response_model=dict[str, Any])
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return aggregate stats for the dashboard."""
    # Get installations for user
    installations_result = await db.execute(
        select(Installation).where(Installation.user_id == current_user.id)
    )
    installation_ids = [i.id for i in installations_result.scalars().all()]

    connected_repos = 0
    total_prs_reviewed = 0
    total_issues_caught = 0
    suggestions_count = 0
    critical_count = 0
    high_count = 0
    medium_count = 0
    low_count = 0
    other_severity_count = 0
    issues_caught_available = True
    issues_caught_reason = None
    total_completed_reviews = 0
    total_failed_reviews = 0

    if installation_ids:
        # Count repos (removed repos keep history but are not "connected")
        repos_result = await db.execute(
            select(func.count(Repository.id)).where(
                Repository.installation_id.in_(installation_ids),
                Repository.removed_at.is_(None),
            )
        )
        connected_repos = repos_result.scalar() or 0

        # Current (non-removed) repos drive connected_repos and the existing
        # review counters. Findings are scoped to ALL repos the user ever
        # owned, so history for removed repositories is preserved.
        current_repo_ids_result = await db.execute(
            select(Repository.id).where(
                Repository.installation_id.in_(installation_ids),
                Repository.removed_at.is_(None),
            )
        )
        current_repo_ids = [r[0] for r in current_repo_ids_result.all()]

        all_repo_ids_result = await db.execute(
            select(Repository.id).where(
                Repository.installation_id.in_(installation_ids),
            )
        )
        all_repo_ids = [r[0] for r in all_repo_ids_result.all()]

        if current_repo_ids:
            # Get PR IDs
            pr_ids_result = await db.execute(
                select(PullRequest.id).where(PullRequest.repo_id.in_(current_repo_ids))
            )
            pr_ids = [r[0] for r in pr_ids_result.all()]

            if pr_ids:
                # Count distinct pull requests that actually have reviews
                prs_reviewed_result = await db.execute(
                    select(func.count(func.distinct(Review.pr_id))).where(
                        Review.pr_id.in_(pr_ids)
                    )
                )
                total_prs_reviewed = prs_reviewed_result.scalar() or 0

            if pr_ids:
                # Count completed reviews
                completed_result = await db.execute(
                    select(func.count(Review.id)).where(
                        Review.pr_id.in_(pr_ids), Review.status == "completed"
                    )
                )
                total_completed_reviews = completed_result.scalar() or 0

                # Count failed reviews
                failed_result = await db.execute(
                    select(func.count(Review.id)).where(
                        Review.pr_id.in_(pr_ids), Review.status == "failed"
                    )
                )
                total_failed_reviews = failed_result.scalar() or 0

        # Unique verified findings across the user's review history. This
        # includes ALL repos the user ever owned — even removed ones — so
        # historical findings are preserved.
        if all_repo_ids:
            all_pr_ids_result = await db.execute(
                select(PullRequest.id).where(PullRequest.repo_id.in_(all_repo_ids))
            )
            all_pr_ids = [r[0] for r in all_pr_ids_result.all()]
            review_ids_result = await db.execute(
                select(Review.id).where(Review.pr_id.in_(all_pr_ids))
            )
            review_ids = [r[0] for r in review_ids_result.all()]

            if review_ids:
                try:
                    findings_result = await db.execute(
                        select(
                            VerificationResultModel.review_id,
                            VerificationResultModel.file_path,
                            VerificationResultModel.line_number,
                            VerificationResultModel.category,
                            VerificationResultModel.severity,
                            VerificationResultModel.description,
                        ).where(
                            VerificationResultModel.review_id.in_(review_ids),
                            VerificationResultModel.is_verified.is_(True),
                        )
                    )
                    findings_rows = findings_result.all()
                except Exception as exc:
                    logger.error(
                        f"Failed to load verified findings for dashboard stats: {exc}",
                        exc_info=True,
                    )
                    findings_rows = []
                    issues_caught_available = False
                    issues_caught_reason = (
                        "Findings data could not be loaded"
                    )

                if issues_caught_available:
                    # De-duplicate reruns of the same review: keep the strongest
                    # severity seen for each stable fingerprint.
                    by_fingerprint: dict[tuple, dict[str, Any]] = {}
                    for (
                        review_id,
                        file_path,
                        line_number,
                        category,
                        severity,
                        description,
                    ) in findings_rows:
                        key = _finding_fingerprint(
                            review_id, file_path, line_number, category, description
                        )
                        current = by_fingerprint.get(key)
                        rank = _SEVERITY_RANK.get(
                            _normalize_severity(severity), 0
                        )
                        if current is None or rank > current["rank"]:
                            by_fingerprint[key] = {
                                "category": (category or "").strip().upper(),
                                "severity": _normalize_severity(severity),
                                "rank": rank,
                            }

                    for entry in by_fingerprint.values():
                        category = entry["category"]
                        severity = entry["severity"]
                        if category == "IMPROVEMENT":
                            suggestions_count += 1
                            continue
                        total_issues_caught += 1
                        if severity == "critical":
                            critical_count += 1
                        elif severity == "high":
                            high_count += 1
                        elif severity == "medium":
                            medium_count += 1
                        elif severity == "low":
                            low_count += 1
                        else:
                            other_severity_count += 1

    return {
        "connected_repos": connected_repos,
        "total_prs_reviewed": total_prs_reviewed,
        "total_issues_caught": total_issues_caught,
        "total_completed_reviews": total_completed_reviews,
        "total_failed_reviews": total_failed_reviews,
        "issues_caught_available": issues_caught_available,
        "issues_caught_reason": issues_caught_reason,
        "suggestions_count": suggestions_count,
        "critical_count": critical_count,
        "high_count": high_count,
        "medium_count": medium_count,
        "low_count": low_count,
        "other_severity_count": other_severity_count,
    }
