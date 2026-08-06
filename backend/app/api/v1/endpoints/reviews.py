import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.github import Installation, PullRequest, Repository
from app.models.review import Review
from app.models.user import User
from app.queue.models import JobStatus
from app.services.github_service import github_service

logger = logging.getLogger(__name__)

router = APIRouter()


def _fmt_dt(dt: datetime | None) -> str | None:
    if not dt:
        return None
    s = dt.isoformat()
    if dt.tzinfo is None and not s.endswith("Z") and "+" not in s:
        s += "Z"
    return s


async def _ensure_review_ownership(
    db: AsyncSession, review: Review, user_id: uuid.UUID
) -> PullRequest:
    pr_result = await db.execute(
        select(PullRequest).where(PullRequest.id == review.pr_id)
    )
    pr = pr_result.scalars().first()
    if not pr:
        raise HTTPException(status_code=404, detail="Review not found")

    repo_result = await db.execute(
        select(Repository).where(Repository.id == pr.repo_id)
    )
    repo_obj = repo_result.scalars().first()
    if not repo_obj:
        raise HTTPException(status_code=404, detail="Review not found")

    install_result = await db.execute(
        select(Installation).where(Installation.id == repo_obj.installation_id)
    )
    install_obj = install_result.scalars().first()
    if not install_obj or install_obj.user_id != user_id:
        raise HTTPException(status_code=404, detail="Review not found")
    return pr


@router.get("", response_model=list[dict[str, Any]])
async def list_reviews(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all reviews across all repos linked to the current user."""
    installations_result = await db.execute(
        select(Installation).where(Installation.user_id == current_user.id)
    )
    installations = installations_result.scalars().all()
    installation_ids = [i.id for i in installations]

    if not installation_ids:
        return []

    repos_result = await db.execute(
        select(Repository).where(
            Repository.installation_id.in_(installation_ids),
            Repository.removed_at.is_(None),
        )
    )
    repos = repos_result.scalars().all()
    repo_ids = [r.id for r in repos]

    if not repo_ids:
        return []

    prs_result = await db.execute(
        select(PullRequest).where(PullRequest.repo_id.in_(repo_ids))
    )
    prs = prs_result.scalars().all()
    pr_id_map = {pr.id: pr for pr in prs}

    if not pr_id_map:
        return []

    reviews_result = await db.execute(
        select(Review)
        .where(Review.pr_id.in_(list(pr_id_map.keys())))
        .order_by(Review.created_at.desc())
        .limit(limit)
    )
    reviews = reviews_result.scalars().all()

    # Build a map of (repo.full_name, pr.pr_number, installation_id) for GitHub batch lookup
    pr_github_lookup: dict[str, dict[str, Any]] = {}
    repo_map = {r.id: r for r in repos}
    install_map = {inst.id: inst for inst in installations}

    for review in reviews:
        pr = pr_id_map.get(review.pr_id)
        if not pr:
            continue
        repo = repo_map.get(pr.repo_id)
        if not repo:
            continue
        install = install_map.get(repo.installation_id)
        if not install:
            continue
        key = f"{repo.full_name}#{pr.pr_number}"
        if key not in pr_github_lookup:
            pr_github_lookup[key] = {
                "repo_full_name": repo.full_name,
                "pr_number": pr.pr_number,
                "installation_id": install.installation_id,
            }

    # Batch fetch PR states from GitHub (with 60s cache)
    pr_github_results: dict[str, dict[str, Any]] = {}
    if pr_github_lookup:
        tasks = {
            key: github_service.get_pull_request(
                info["repo_full_name"], info["pr_number"], info["installation_id"]
            )
            for key, info in pr_github_lookup.items()
        }
        for key, coro in tasks.items():
            try:
                pr_github_results[key] = await coro
            except Exception:
                pr_github_results[key] = {"state": "unknown"}

    # Check which PRs have active reviews (queued/running).
    # Only the NEWEST non-terminal review per PR counts — superseded or
    # orphaned reviews never hold the active-review lock.
    active_pr_ids: set[uuid.UUID] = set()
    active_result = await db.execute(
        select(Review)
        .where(
            Review.pr_id.in_(list(pr_id_map.keys())),
            Review.status.in_(["queued", "pending", "running"]),
        )
        .order_by(Review.created_at.desc())
    )
    for rv in active_result.scalars().all():
        if rv.pr_id not in active_pr_ids:
            active_pr_ids.add(rv.pr_id)

    result = []
    for review in reviews:
        pr = pr_id_map.get(review.pr_id)
        if not pr:
            continue
        repo = repo_map.get(pr.repo_id, {})
        install = (
            install_map.get(repo.installation_id)
            if hasattr(repo, "installation_id")
            else None
        )
        gh_key = f"{getattr(repo, 'full_name', '')}#{pr.pr_number}" if repo else ""
        gh_state = (
            pr_github_results.get(gh_key, {}).get("state", "unknown")
            if gh_key
            else "unknown"
        )

        result.append(
            {
                "id": str(review.id),
                "status": review.status,
                "summary": review.summary,
                "stats": review.stats or {},
                "started_at": _fmt_dt(review.started_at),
                "completed_at": _fmt_dt(review.completed_at),
                "error_message": review.error_message,
                "created_at": _fmt_dt(review.created_at),
                "github_pr_state": gh_state,
                "pr_has_active_review": review.pr_id in active_pr_ids,
                "pull_request": {
                    "id": str(pr.id),
                    "pr_number": pr.pr_number,
                    "title": pr.title,
                    "author": pr.author,
                    "status": pr.status,
                    "head_branch": pr.head_branch,
                    "base_branch": pr.base_branch,
                    "additions": pr.additions,
                    "deletions": pr.deletions,
                    "changed_files": pr.changed_files,
                },
                "repository": {
                    "id": str(pr.repo_id),
                    "name": getattr(repo, "name", "") if hasattr(repo, "name") else "",
                    "full_name": (
                        getattr(repo, "full_name", "")
                        if hasattr(repo, "full_name")
                        else ""
                    ),
                },
            }
        )

    return result


@router.get("/{review_id}", response_model=dict[str, Any])
async def get_review(
    review_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single review detail by ID."""
    try:
        rid = uuid.UUID(review_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid review ID")

    review_result = await db.execute(select(Review).where(Review.id == rid))
    review = review_result.scalars().first()

    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    pr = await _ensure_review_ownership(db, review, current_user.id)

    repo_info = {}
    installation_id = None
    if pr:
        repo_result = await db.execute(
            select(Repository).where(Repository.id == pr.repo_id)
        )
        repo = repo_result.scalars().first()
        if repo:
            repo_info = {"name": repo.name, "full_name": repo.full_name}
            installation_id = repo.installation_id

    # Check if another review for this PR is already active.
    # Only the NEWEST non-terminal review per PR holds the lock — superseded
    # or orphaned reviews never block (Issue 5: lock exists only while active).
    pr_has_active = False
    if pr:
        other_active = await db.execute(
            select(Review)
            .where(
                Review.pr_id == pr.id,
                Review.status.in_(["queued", "pending", "running"]),
            )
            .order_by(Review.created_at.desc())
            .limit(1)
        )
        latest_active = other_active.scalars().first()
        if latest_active and latest_active.id != rid:
            pr_has_active = True

    # Latest execution for this PR (the most recent review, regardless of status)
    latest_review_id = None
    if pr:
        latest_res = await db.execute(
            select(Review.id)
            .where(Review.pr_id == pr.id)
            .order_by(Review.created_at.desc())
            .limit(1)
        )
        latest_review_id = latest_res.scalars().first()
        latest_review_id = str(latest_review_id) if latest_review_id else None

    # Real-time GitHub PR state
    gh_state = "unknown"
    if pr and repo_info.get("full_name") and installation_id:
        try:
            from app.services.github_service import github_service

            gh_result = await github_service.get_pull_request(
                repo_info["full_name"], pr.pr_number, installation_id
            )
            gh_state = gh_result.get("state", "unknown")
        except Exception:
            gh_state = "unknown"

    from app.services.review_execution_service import get_latest_execution
    current_execution = await get_latest_execution(db, review.id)

    return {
        "id": str(review.id),
        "status": review.status,
        "summary": review.summary,
        "stats": review.stats or {},
        "started_at": _fmt_dt(review.started_at),
        "completed_at": _fmt_dt(review.completed_at),
        "error_message": review.error_message,
        "created_at": _fmt_dt(review.created_at),
        "github_pr_state": gh_state,
        "pr_has_active_review": pr_has_active,
        "latest_review_id": latest_review_id,
        "pull_request": (
            {
                "id": str(pr.id) if pr else None,
                "pr_number": pr.pr_number if pr else None,
                "title": pr.title if pr else None,
                "author": pr.author if pr else None,
                "status": pr.status if pr else None,
                "head_branch": pr.head_branch if pr else None,
                "base_branch": pr.base_branch if pr else None,
                "additions": pr.additions if pr else None,
                "deletions": pr.deletions if pr else None,
                "changed_files": pr.changed_files if pr else None,
            }
            if pr
            else None
        ),
        "repository": repo_info,
        "current_execution": (
            {
                "execution_number": current_execution.execution_number,
                "status": current_execution.status,
                "provider": current_execution.provider,
                "model": current_execution.model,
            }
            if current_execution
            else None
        ),
    }


@router.post("/{review_id}/cancel", response_model=dict[str, Any])
async def cancel_review(
    review_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cancel an ongoing review and immediately close the GitHub check run."""
    try:
        rid = uuid.UUID(review_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid review ID")

    review_result = await db.execute(select(Review).where(Review.id == rid))
    review = review_result.scalars().first()

    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    pr = await _ensure_review_ownership(db, review, current_user.id)

    if review.status not in ["pending", "running", "queued"]:
        return {"status": "success", "message": "Review already in terminal state"}

    # 1. Mark the Review as cancelled in our DB
    await db.execute(
        update(Review)
        .where(Review.id == rid)
        .values(status="cancelled", error_message="Cancelled by user")
    )
    from app.services.review_execution_service import mark_execution_final

    await mark_execution_final(db, rid, "cancelled")

    if pr:
        # 2a. Cancel the background job for THIS review.
        # Lifecycle jobs embed the review ID in delivery_id ("{action}-{review_id}").
        # Fall back to repo+PR match for webhook jobs (delivery GUID has no review link).
        from app.queue.models import ReviewJob

        job_cancel = await db.execute(
            update(ReviewJob)
            .where(
                ReviewJob.repo_id == pr.repo_id,
                ReviewJob.pr_number == pr.pr_number,
                ReviewJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
                ReviewJob.delivery_id.like(f"%-{rid}"),
            )
            .values(status=JobStatus.CANCELLED)
        )
        if job_cancel.rowcount == 0:
            await db.execute(
                update(ReviewJob)
                .where(
                    ReviewJob.repo_id == pr.repo_id,
                    ReviewJob.pr_number == pr.pr_number,
                    ReviewJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
                )
                .values(status=JobStatus.CANCELLED)
            )

        # 2b. Tell GitHub to close the check run as "cancelled"
        check_run_id = review.github_check_run_id
        if check_run_id:
            try:
                repo_result = await db.execute(
                    select(Repository).where(Repository.id == pr.repo_id)
                )
                repo = repo_result.scalars().first()

                if repo:
                    install_result = await db.execute(
                        select(Installation).where(
                            Installation.id == repo.installation_id
                        )
                    )
                    installation = install_result.scalars().first()

                    if installation:
                        from app.github.client import GitHubClient

                        owner, repo_name = repo.full_name.split("/", 1)
                        try:
                            await GitHubClient().update_check_run(
                                installation_id=installation.installation_id,
                                owner=owner,
                                repo=repo_name,
                                check_run_id=check_run_id,
                                status="completed",
                                output={
                                    "title": "Revora Review Cancelled",
                                    "summary": "The review was cancelled by the user.",
                                    "conclusion": "cancelled",
                                },
                            )
                            logger.info(
                                f"Closed GitHub check run {check_run_id} as cancelled for review {review_id}"
                            )
                        except Exception as e:
                            logger.warning(
                                f"Failed to close GitHub check run on cancel: {e}"
                            )
            except Exception as e:
                logger.error(f"Unexpected error in cancel_review DB lookup: {e}")

    await db.commit()

    return {"status": "success", "message": "Review cancelled"}
