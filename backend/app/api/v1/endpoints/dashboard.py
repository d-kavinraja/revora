from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Dict, Any

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.github import Installation, Repository, PullRequest
from app.models.review import Review

router = APIRouter()


@router.get("/stats", response_model=Dict[str, Any])
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
    total_completed_reviews = 0
    total_failed_reviews = 0

    if installation_ids:
        # Count repos
        repos_result = await db.execute(
            select(func.count(Repository.id)).where(
                Repository.installation_id.in_(installation_ids)
            )
        )
        connected_repos = repos_result.scalar() or 0

        # Get repo IDs
        repo_ids_result = await db.execute(
            select(Repository.id).where(
                Repository.installation_id.in_(installation_ids)
            )
        )
        repo_ids = [r[0] for r in repo_ids_result.all()]

        if repo_ids:
            # Count pull requests
            prs_result = await db.execute(
                select(func.count(PullRequest.id)).where(PullRequest.repo_id.in_(repo_ids))
            )
            total_prs_reviewed = prs_result.scalar() or 0

            # Get PR IDs
            pr_ids_result = await db.execute(
                select(PullRequest.id).where(PullRequest.repo_id.in_(repo_ids))
            )
            pr_ids = [r[0] for r in pr_ids_result.all()]

            if pr_ids:
                # Count completed reviews
                completed_result = await db.execute(
                    select(func.count(Review.id)).where(
                        Review.pr_id.in_(pr_ids),
                        Review.status == "completed"
                    )
                )
                total_completed_reviews = completed_result.scalar() or 0

                # Count failed reviews
                failed_result = await db.execute(
                    select(func.count(Review.id)).where(
                        Review.pr_id.in_(pr_ids),
                        Review.status == "failed"
                    )
                )
                total_failed_reviews = failed_result.scalar() or 0

                # Approximate issues caught from stats JSONB
                # Sum bug_count + security_count + performance_count from stats
                reviews_result = await db.execute(
                    select(Review.stats).where(
                        Review.pr_id.in_(pr_ids),
                        Review.status == "completed"
                    )
                )
                for (stats_row,) in reviews_result.all():
                    if stats_row:
                        total_issues_caught += (
                            (stats_row.get("bug_count") or 0) +
                            (stats_row.get("security_count") or 0) +
                            (stats_row.get("performance_count") or 0)
                        )

    return {
        "connected_repos": connected_repos,
        "total_prs_reviewed": total_prs_reviewed,
        "total_issues_caught": total_issues_caught,
        "total_completed_reviews": total_completed_reviews,
        "total_failed_reviews": total_failed_reviews,
    }
