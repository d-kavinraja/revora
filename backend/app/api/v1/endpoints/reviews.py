from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Any, Dict
import uuid

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.github import Installation, Repository, PullRequest
from app.models.review import Review

router = APIRouter()


@router.get("", response_model=List[Dict[str, Any]])
async def list_reviews(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all reviews across all repos linked to the current user."""
    # Get all installations for this user
    installations_result = await db.execute(
        select(Installation).where(Installation.user_id == current_user.id)
    )
    installations = installations_result.scalars().all()
    installation_ids = [i.id for i in installations]

    if not installation_ids:
        return []

    # Get repo ids
    repos_result = await db.execute(
        select(Repository.id, Repository.full_name, Repository.name).where(
            Repository.installation_id.in_(installation_ids)
        )
    )
    repo_rows = repos_result.all()
    repo_id_map = {r[0]: {"full_name": r[1], "name": r[2]} for r in repo_rows}
    repo_ids = list(repo_id_map.keys())

    if not repo_ids:
        return []

    # Get pull requests for those repos
    prs_result = await db.execute(
        select(PullRequest).where(PullRequest.repo_id.in_(repo_ids))
    )
    prs = prs_result.scalars().all()
    pr_id_map = {pr.id: pr for pr in prs}

    if not pr_id_map:
        return []

    # Get reviews for those PRs, ordered by newest
    reviews_result = await db.execute(
        select(Review)
        .where(Review.pr_id.in_(list(pr_id_map.keys())))
        .order_by(Review.created_at.desc())
        .limit(limit)
    )
    reviews = reviews_result.scalars().all()

    result = []
    for review in reviews:
        pr = pr_id_map.get(review.pr_id)
        if not pr:
            continue
        repo_info = repo_id_map.get(pr.repo_id, {})
        result.append(
            {
                "id": str(review.id),
                "status": review.status,
                "summary": review.summary,
                "stats": review.stats or {},
                "started_at": (
                    review.started_at.isoformat() if review.started_at else None
                ),
                "completed_at": (
                    review.completed_at.isoformat() if review.completed_at else None
                ),
                "error_message": review.error_message,
                "created_at": (
                    review.created_at.isoformat() if review.created_at else None
                ),
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
                    "name": repo_info.get("name", ""),
                    "full_name": repo_info.get("full_name", ""),
                },
            }
        )

    return result


@router.get("/{review_id}", response_model=Dict[str, Any])
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

    # Get PR
    pr_result = await db.execute(
        select(PullRequest).where(PullRequest.id == review.pr_id)
    )
    pr = pr_result.scalars().first()

    # Get repo info
    repo_info = {}
    if pr:
        repo_result = await db.execute(
            select(Repository).where(Repository.id == pr.repo_id)
        )
        repo = repo_result.scalars().first()
        if repo:
            repo_info = {"name": repo.name, "full_name": repo.full_name}

    return {
        "id": str(review.id),
        "status": review.status,
        "summary": review.summary,
        "stats": review.stats or {},
        "started_at": review.started_at.isoformat() if review.started_at else None,
        "completed_at": (
            review.completed_at.isoformat() if review.completed_at else None
        ),
        "error_message": review.error_message,
        "created_at": review.created_at.isoformat() if review.created_at else None,
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
    }
