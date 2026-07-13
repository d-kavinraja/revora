from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Any, Dict, Optional
import uuid
import httpx
from datetime import datetime, timezone
from pydantic import BaseModel

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.github import Installation, Repository, PullRequest
from app.models.review import Review
from app.github.auth import github_app_auth
from app.services.api_key_service import api_key_service

router = APIRouter()


@router.get("", response_model=List[Dict[str, Any]])
async def list_repositories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all repositories linked to the current user's installations."""
    # Get all installations for this user
    installations_result = await db.execute(
        select(Installation).where(Installation.user_id == current_user.id)
    )
    installations = installations_result.scalars().all()
    installation_ids = [i.id for i in installations]

    if not installation_ids:
        return []

    # Get repositories linked to those installations
    repos_result = await db.execute(
        select(Repository).where(Repository.installation_id.in_(installation_ids))
    )
    repos = repos_result.scalars().all()

    result = []
    for repo in repos:
        # Count reviews for this repo via pull_requests
        pr_ids_result = await db.execute(
            select(PullRequest.id).where(PullRequest.repo_id == repo.id)
        )
        pr_ids = [r[0] for r in pr_ids_result.all()]

        total_reviews = 0
        if pr_ids:
            count_result = await db.execute(
                select(func.count(Review.id)).where(Review.pr_id.in_(pr_ids))
            )
            total_reviews = count_result.scalar() or 0

        result.append({
            "id": str(repo.id),
            "name": repo.name,
            "full_name": repo.full_name,
            "description": repo.description,
            "language": repo.language,
            "is_private": repo.is_private,
            "reviews_enabled": repo.reviews_enabled,
            "total_reviews": total_reviews,
            "last_synced_at": repo.last_synced_at.isoformat() if repo.last_synced_at else None,
            "settings": repo.settings or {},
        })

    return result


@router.post("/sync-all", response_model=dict)
async def sync_all_repositories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Fetch and sync connected repositories directly from GitHub API for all installations of this user."""
    # Get all installations for this user
    installations_result = await db.execute(
        select(Installation).where(Installation.user_id == current_user.id)
    )
    installations = installations_result.scalars().all()
    
    if not installations:
        return {
            "status": "success",
            "message": "No installations found for this user. Please install the GitHub App first.",
            "synced": []
        }

    synced_repos = []
    async with httpx.AsyncClient() as client:
        for inst in installations:
            try:
                # Retrieve Installation Access Token
                token = await github_app_auth.get_installation_token(inst.installation_id)
                
                # Fetch repositories for this installation from GitHub
                repos_res = await client.get(
                    "https://api.github.com/installation/repositories",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    }
                )
                
                if not repos_res.is_success:
                    print(f"Failed to fetch repositories for installation {inst.installation_id}: {repos_res.text}")
                    continue
                
                repos_data = repos_res.json().get("repositories", [])
                for r in repos_data:
                    repo_gid = r.get("id")
                    res = await db.execute(select(Repository).where(Repository.github_id == repo_gid))
                    db_repo = res.scalars().first()
                    
                    if not db_repo:
                        db_repo = Repository(
                            github_id=repo_gid,
                            name=r.get("name"),
                            full_name=r.get("full_name"),
                            description=r.get("description"),
                            language=r.get("language"),
                            is_private=r.get("private", False),
                            installation_id=inst.id,
                            reviews_enabled=True,
                            last_synced_at=datetime.now(timezone.utc)
                        )
                        db.add(db_repo)
                        print(f"Synced new repository {r.get('full_name')} from API.")
                    else:
                        db_repo.installation_id = inst.id
                        db_repo.name = r.get("name")
                        db_repo.full_name = r.get("full_name")
                        db_repo.description = r.get("description")
                        db_repo.language = r.get("language")
                        db_repo.is_private = r.get("private", False)
                        db_repo.last_synced_at = datetime.now(timezone.utc)
                        db.add(db_repo)
                        print(f"Updated repository {r.get('full_name')} from API.")
                    
                    synced_repos.append(r.get("full_name"))
                    
            except Exception as e:
                print(f"Error syncing repositories for installation {inst.installation_id}: {e}")

        await db.commit()

    return {
        "status": "success",
        "message": f"Successfully synced {len(synced_repos)} repositories from GitHub.",
        "synced": synced_repos
    }


@router.post("/{repo_id}/sync", response_model=dict)
async def sync_repository(
    repo_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Sync pull requests and bot reviews (Revora, CodeRabbit, etc.) from GitHub."""
    try:
        try:
            rid = uuid.UUID(repo_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid repository ID")

        # Get repo
        repo_result = await db.execute(select(Repository).where(Repository.id == rid))
        repo = repo_result.scalars().first()
        if not repo:
            raise HTTPException(status_code=404, detail="Repository not found")

        # Get installation
        inst_result = await db.execute(select(Installation).where(Installation.id == repo.installation_id))
        installation = inst_result.scalars().first()
        if not installation:
            raise HTTPException(status_code=404, detail="GitHub App Installation not found for this repository.")

        # Get GitHub installation token
        try:
            token = await github_app_auth.get_installation_token(installation.installation_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to authenticate with GitHub App: {e}")

        # Parse owner and repo name
        parts = repo.full_name.split("/")
        if len(parts) != 2:
            raise HTTPException(status_code=400, detail="Invalid repository full name format.")
        owner, repo_name = parts

        async with httpx.AsyncClient() as client:
            # 1. Fetch Pull Requests from GitHub
            pulls_url = f"https://api.github.com/repos/{owner}/{repo_name}/pulls"
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            
            # Get both open and closed PRs
            pulls_res = await client.get(f"{pulls_url}?state=all&per_page=50", headers=headers)
            if not pulls_res.is_success:
                raise HTTPException(status_code=400, detail="Failed to fetch pull requests from GitHub.")
            
            gh_pulls = pulls_res.json()
            imported_prs = 0
            imported_reviews = 0
            triggered_reviews = 0

            for gh_pr in gh_pulls:
                pr_number = gh_pr["number"]
                title = gh_pr["title"]
                author = gh_pr["user"]["login"]
                head_sha = gh_pr["head"]["sha"]
                base_branch = gh_pr["base"]["ref"]
                head_branch = gh_pr["head"]["ref"]
                status_str = gh_pr["state"] # open or closed
                
                # Fetch detailed PR for additions/deletions
                detail_res = await client.get(f"{pulls_url}/{pr_number}", headers=headers)
                additions, deletions, changed_files = 0, 0, 0
                if detail_res.is_success:
                    detail_data = detail_res.json()
                    additions = detail_data.get("additions", 0)
                    deletions = detail_data.get("deletions", 0)
                    changed_files = detail_data.get("changed_files", 0)

                # Get or create PullRequest
                pr_check = await db.execute(
                    select(PullRequest).where(
                        PullRequest.repo_id == repo.id,
                        PullRequest.pr_number == pr_number
                    )
                )
                db_pr = pr_check.scalars().first()

                if not db_pr:
                    db_pr = PullRequest(
                        repo_id=repo.id,
                        pr_number=pr_number,
                        title=title,
                        author=author,
                        head_sha=head_sha,
                        base_branch=base_branch,
                        head_branch=head_branch,
                        status=status_str,
                        additions=additions,
                        deletions=deletions,
                        changed_files=changed_files
                    )
                    db.add(db_pr)
                    await db.commit()
                    await db.refresh(db_pr)
                else:
                    db_pr.status = status_str
                    db_pr.title = title
                    db_pr.head_sha = head_sha
                    db_pr.additions = additions
                    db_pr.deletions = deletions
                    db_pr.changed_files = changed_files
                    db.add(db_pr)
                    await db.commit()

                imported_prs += 1

                # 2. Fetch Reviews for this PR to import bot reviews (Revora, CodeRabbit, etc.)
                reviews_res = await client.get(f"{pulls_url}/{pr_number}/reviews", headers=headers)
                has_bot_review = False
                if reviews_res.is_success:
                    gh_reviews = reviews_res.json()
                    for gh_review in gh_reviews:
                        body = gh_review.get("body") or ""
                        reviewer_login = gh_review.get("user", {}).get("login", "")
                        
                        # Identify bot reviews (Revora, CodeRabbit, coderabbitai, or check if body looks like AI review)
                        is_bot = (
                            "coderabbit" in reviewer_login.lower() or
                            "revora" in reviewer_login.lower() or
                            "coderabbit" in body.lower() or
                            "revora" in body.lower() or
                            "gemini" in body.lower() or
                            reviewer_login.endswith("[bot]")
                        )
                        
                        if is_bot and body.strip():
                            has_bot_review = True
                            # Check if we already imported this review
                            rev_check = await db.execute(
                                select(Review).where(
                                    Review.pr_id == db_pr.id,
                                    Review.summary == body
                                )
                            )
                            db_review = rev_check.scalars().first()

                            if not db_review:
                                db_review = Review(
                                    pr_id=db_pr.id,
                                    status="completed",
                                    summary=body,
                                    started_at=db_pr.created_at,
                                    completed_at=datetime.now(timezone.utc),
                                    stats={
                                        "provider": "imported",
                                        "model": reviewer_login,
                                    }
                                )
                                db.add(db_review)
                                await db.commit()
                                imported_reviews += 1

                # Check if we have any review (completed, failed, or running) for this PR locally
                local_rev_check = await db.execute(
                    select(Review).where(Review.pr_id == db_pr.id)
                )
                local_review = local_rev_check.scalars().first()

                if not has_bot_review and not local_review:
                    # Trigger Revora review pipeline in background
                    import asyncio
                    from app.github.webhooks import run_pr_review_pipeline
                    
                    payload = {
                        "installation": {"id": installation.installation_id},
                        "repository": {
                            "owner": {"login": owner},
                            "name": repo_name,
                            "full_name": repo.full_name,
                            "private": repo.is_private,
                            "id": repo.github_id,
                        },
                        "pull_request": {
                            "number": pr_number,
                            "title": title,
                            "body": gh_pr.get("body", "") or "",
                            "head": {"sha": head_sha, "ref": head_branch},
                            "base": {"ref": base_branch},
                            "user": {"login": author},
                            "additions": additions,
                            "deletions": deletions,
                            "changed_files": changed_files,
                        }
                    }
                    asyncio.create_task(run_pr_review_pipeline(payload, f"sync-{pr_number}"))
                    triggered_reviews += 1

            # Update last synced time
            repo.last_synced_at = datetime.now(timezone.utc)
            db.add(repo)
            await db.commit()

            return {
                "status": "success",
                "message": f"Successfully synced repository. Synced {imported_prs} PRs, imported {imported_reviews} bot reviews, and triggered {triggered_reviews} new reviews in the background."
            }

    except Exception as e:
        print(f"Error syncing repository: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to sync repository: {e}")


# --- Repository Model Configuration ---


class RepoConfigUpdate(BaseModel):
    assigned_provider: Optional[str] = None
    assigned_model: Optional[str] = None
    assigned_key_id: Optional[str] = None
    reviews_enabled: Optional[bool] = None


PROVIDER_MODELS = {
    "gemini": ["gemini-3.5-flash", "gemini-3.5-pro", "gemini-3.1-flash-lite"],
    "openai": ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"],
    "anthropic": ["anthropic/claude-sonnet-4-20250514", "anthropic/claude-3-5-haiku-20241022"],
    "deepseek": ["deepseek/deepseek-chat", "deepseek/deepseek-coder"],
    "groq": ["groq/llama-3.3-70b-versatile"],
}


@router.get("/available-models", response_model=Dict[str, List[str]])
async def get_available_models(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return LLM models available based on the user's active API keys."""
    api_keys = await api_key_service.get_all_for_user(db, current_user.id)
    active_providers = {key.provider.lower() for key in api_keys if key.is_valid}

    available = {}
    for provider, models in PROVIDER_MODELS.items():
        if provider in active_providers:
            available[provider] = models

    return available


@router.patch("/{repo_id}/config", response_model=Dict[str, Any])
async def update_repository_config(
    repo_id: str,
    config: RepoConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update repository model configuration and review settings."""
    try:
        rid = uuid.UUID(repo_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid repository ID")

    # Verify repo belongs to user's installations
    installations_result = await db.execute(
        select(Installation).where(Installation.user_id == current_user.id)
    )
    installation_ids = [i.id for i in installations_result.scalars().all()]

    repo_result = await db.execute(
        select(Repository).where(
            Repository.id == rid,
            Repository.installation_id.in_(installation_ids),
        )
    )
    repo = repo_result.scalars().first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    # Update fields
    if config.reviews_enabled is not None:
        repo.reviews_enabled = config.reviews_enabled

    settings = dict(repo.settings or {})
    if config.assigned_provider is not None:
        settings["assigned_provider"] = config.assigned_provider
    if config.assigned_model is not None:
        settings["assigned_model"] = config.assigned_model
    if config.assigned_key_id is not None:
        settings["assigned_key_id"] = config.assigned_key_id
    repo.settings = settings

    db.add(repo)
    await db.commit()
    await db.refresh(repo)

    # Count reviews
    pr_ids_result = await db.execute(
        select(PullRequest.id).where(PullRequest.repo_id == repo.id)
    )
    pr_ids = [r[0] for r in pr_ids_result.all()]
    total_reviews = 0
    if pr_ids:
        count_result = await db.execute(
            select(func.count(Review.id)).where(Review.pr_id.in_(pr_ids))
        )
        total_reviews = count_result.scalar() or 0

    return {
        "id": str(repo.id),
        "name": repo.name,
        "full_name": repo.full_name,
        "description": repo.description,
        "language": repo.language,
        "is_private": repo.is_private,
        "reviews_enabled": repo.reviews_enabled,
        "total_reviews": total_reviews,
        "last_synced_at": repo.last_synced_at.isoformat() if repo.last_synced_at else None,
        "settings": repo.settings or {},
    }
