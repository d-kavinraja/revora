import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.github.auth import github_app_auth
from app.models.github import Installation, PullRequest, Repository
from app.models.review import Review
from app.models.sync_run import SyncRun
from app.models.user import User
from app.services.api_key_service import api_key_service
from app.services.repository_service import repository_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=list[dict[str, Any]])
async def list_repositories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    include_removed: bool = False,
):
    """Return the current user's repositories.

    Active repositories by default. Pass include_removed=true to include
    removed (uninstalled) repositories — they keep their full review history
    and are reported with a "removed" status, removed_at and last-reviewed
    metadata so traceability is preserved while active lists stay clean.
    """
    # Get all installations for this user
    installations_result = await db.execute(
        select(Installation).where(Installation.user_id == current_user.id)
    )
    installations = installations_result.scalars().all()
    installation_ids = [i.id for i in installations]

    if not installation_ids:
        return []

    q = select(Repository).where(Repository.installation_id.in_(installation_ids))
    if include_removed:
        q = q.where(Repository.removed_at.isnot(None)).order_by(
            Repository.removed_at.desc()
        )
    else:
        q = q.where(Repository.removed_at.is_(None)).order_by(
            Repository.full_name.asc()
        )
    repos_result = await db.execute(q)
    repos = repos_result.scalars().all()

    inst_by_id = {i.id: i for i in installations}

    result = []
    for repo in repos:
        # Count reviews & check active review status for this repo via pull_requests
        pr_ids_result = await db.execute(
            select(PullRequest.id).where(PullRequest.repo_id == repo.id)
        )
        pr_ids = [r[0] for r in pr_ids_result.all()]

        total_reviews = 0
        active_review_status = None
        last_reviewed_at = None
        if pr_ids:
            count_result = await db.execute(
                select(func.count(Review.id)).where(Review.pr_id.in_(pr_ids))
            )
            total_reviews = count_result.scalar() or 0

            active_rev_result = await db.execute(
                select(Review.status)
                .where(
                    Review.pr_id.in_(pr_ids),
                    Review.status.in_(["queued", "pending", "running"]),
                )
                .order_by(Review.created_at.desc())
            )
            active_review_status = active_rev_result.scalars().first()

            last_review_result = await db.execute(
                select(func.max(Review.completed_at)).where(
                    Review.pr_id.in_(pr_ids),
                    Review.status == "completed",
                )
            )
            last_reviewed_at = last_review_result.scalar()

        inst = inst_by_id.get(repo.installation_id)

        # Status: removed | permission_required | disabled | active
        status = "active"
        if repo.removed_at is not None:
            status = "removed"
        elif inst is not None and not inst.permissions_ok:
            status = "permission_required"
        elif not repo.reviews_enabled:
            status = "disabled"

        result.append(
            {
                "id": str(repo.id),
                "name": repo.name,
                "full_name": repo.full_name,
                "description": repo.description,
                "language": repo.language,
                "is_private": repo.is_private,
                "is_archived": repo.is_archived,
                "reviews_enabled": repo.reviews_enabled,
                "status": status,
                "removed_at": repo.removed_at.isoformat() if repo.removed_at else None,
                "total_reviews": total_reviews,
                "active_review_status": active_review_status,
                "last_reviewed_at": (
                    last_reviewed_at.isoformat() if last_reviewed_at else None
                ),
                "last_synced_at": (
                    repo.last_synced_at.isoformat() if repo.last_synced_at else None
                ),
                "settings": repo.settings or {},
                "permissions_ok": bool(inst.permissions_ok) if inst else True,
                "last_sync": (
                    {
                        "completed_at": (
                            inst.last_sync_completed_at.isoformat()
                            if inst and inst.last_sync_completed_at
                            else None
                        ),
                        "status": inst.last_sync_status if inst else None,
                        "error": inst.last_sync_error if inst else None,
                        "reason": inst.last_sync_reason if inst else None,
                    }
                    if inst
                    else None
                ),
            }
        )

    return result


@router.post("/sync-all", response_model=dict)
async def sync_all_repositories(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
):
    """Fetch and sync connected repositories directly from GitHub API for all installations of this user.

    Delegates to the sync engine (manual reason): repositories added/updated/
    removed, PRs reconciled, missed reviews enqueued — with the same
    history-preserving semantics as the automatic recovery passes.
    """
    try:
        result = await repository_service.refresh_installation(db, current_user.id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sync repositories: {e}")


@router.post("/{repo_id}/sync", response_model=dict)
async def sync_repository(
    repo_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
        if repo.removed_at is not None:
            raise HTTPException(
                status_code=400,
                detail="Repository was removed from Revora. Re-add it by installing the GitHub App before syncing.",
            )

        # Get installation
        inst_result = await db.execute(
            select(Installation).where(Installation.id == repo.installation_id)
        )
        installation = inst_result.scalars().first()
        if not installation:
            raise HTTPException(
                status_code=404,
                detail="GitHub App Installation not found for this repository.",
            )

        # Get GitHub installation token
        try:
            token = await github_app_auth.get_installation_token(
                installation.installation_id
            )
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to authenticate with GitHub App: {e}"
            )

        # Parse owner and repo name
        parts = repo.full_name.split("/")
        if len(parts) != 2:
            raise HTTPException(
                status_code=400, detail="Invalid repository full name format."
            )
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
            pulls_res = await client.get(
                f"{pulls_url}?state=all&per_page=50", headers=headers
            )
            if not pulls_res.is_success:
                raise HTTPException(
                    status_code=400, detail="Failed to fetch pull requests from GitHub."
                )

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
                status_str = gh_pr["state"]  # open or closed

                # Fetch detailed PR for additions/deletions
                detail_res = await client.get(
                    f"{pulls_url}/{pr_number}", headers=headers
                )
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
                        PullRequest.pr_number == pr_number,
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
                        changed_files=changed_files,
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
                reviews_res = await client.get(
                    f"{pulls_url}/{pr_number}/reviews", headers=headers
                )
                has_bot_review = False
                if reviews_res.is_success:
                    gh_reviews = reviews_res.json()
                    for gh_review in gh_reviews:
                        body = gh_review.get("body") or ""
                        reviewer_login = gh_review.get("user", {}).get("login", "")

                        # Identify bot reviews (Revora, CodeRabbit, coderabbitai, or check if body looks like AI review)
                        is_bot = (
                            "coderabbit" in reviewer_login.lower()
                            or "revora" in reviewer_login.lower()
                            or "coderabbit" in body.lower()
                            or "revora" in body.lower()
                            or "gemini" in body.lower()
                            or reviewer_login.endswith("[bot]")
                        )

                        if is_bot and body.strip():
                            has_bot_review = True
                            # Check if we already imported this review
                            rev_check = await db.execute(
                                select(Review).where(
                                    Review.pr_id == db_pr.id, Review.summary == body
                                )
                            )
                            db_review = rev_check.scalars().first()

                            if not db_review:
                                db_review = Review(
                                    pr_id=db_pr.id,
                                    status="completed",
                                    summary=body,
                                    started_at=db_pr.created_at,
                                    completed_at=datetime.now(UTC),
                                    stats={
                                        "provider": "imported",
                                        "model": reviewer_login,
                                    },
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
                    # Trigger Revora review pipeline via Postgres queue.
                    # Guard: if this exact commit was already reviewed (by a
                    # webhook or a previous sync), skip — no duplicate reviews.
                    from app.services.sync_engine import _execution_exists_for_sha

                    if await _execution_exists_for_sha(db, db_pr.id, head_sha):
                        logger.info(
                            f"PR #{pr_number} already reviewed at {head_sha[:12]} — sync skipped trigger"
                        )
                    else:
                        from app.queue.dispatcher import enqueue_review_job
                        from app.services.sync_engine import sync_delivery_id

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
                            },
                        }
                        job = await enqueue_review_job(
                            db,
                            payload,
                            sync_delivery_id(repo.github_id, pr_number, head_sha),
                        )
                        if job:
                            triggered_reviews += 1

            # Update last synced time
            repo.last_synced_at = datetime.now(UTC)
            db.add(repo)
            await db.commit()

            return {
                "status": "success",
                "message": f"Successfully synced repository. Synced {imported_prs} PRs, imported {imported_reviews} bot reviews, and triggered {triggered_reviews} new reviews in the background.",
            }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error syncing repository: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to sync repository: {e}")


# --- Repository Model Configuration ---


class RepoConfigUpdate(BaseModel):
    assigned_provider: str | None = None
    assigned_model: str | None = None
    assigned_key_id: str | None = None
    reviews_enabled: bool | None = None


# PROVIDER_MODELS is now dynamically queried via ModelDiscoveryEngine.


@router.get("/available-models", response_model=dict[str, list[dict[str, Any]]])
async def get_available_models(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return live LLM models available from the user's actual API keys by querying each provider endpoint."""
    import logging as _logging

    from app.core.security import encryption_service
    from app.services.model_discovery import model_discovery_engine
    from app.ai.discovery.engine import discovery_engine

    logger = _logging.getLogger(__name__)

    api_keys_list = await api_key_service.get_all_for_user(db, current_user.id)
    # Build a dict of provider -> decrypted api key (valid keys only)
    provider_keys: dict[str, str] = {}
    for key_obj in api_keys_list:
        if key_obj.is_valid:
            try:
                provider_keys[key_obj.provider.lower()] = encryption_service.decrypt(
                    key_obj.encrypted_key
                )
            except Exception:
                pass

    available: dict[str, list[dict[str, Any]]] = {}

    for provider, raw_key in provider_keys.items():
        try:
            if provider == "openrouter":
                # Ensure the models are synced using our dynamic engine
                try:
                    db_models = await discovery_engine.sync_provider_models(db, provider, force=False)
                except Exception:
                    db_models = await discovery_engine.get_cached_models(db, provider)
                
                models = [
                    {
                        "model_name": m.model_id,
                        "canonical_model_name": m.model_id,
                        "accessible": True,
                        "deprecated": False,
                        "preview": False,
                        "enterprise_only": False,
                        "metadata": {"description": m.description, "context_window": m.context_window, "is_free": m.is_free}
                    }
                    for m in db_models
                ]
            else:
                models = await model_discovery_engine.get_available_models(
                    provider, raw_key
                )
                
            if models:
                # Sort by model_name
                available[provider] = sorted(models, key=lambda x: x["model_name"])
        except Exception as e:
            logger.warning(f"Live model fetch failed for provider '{provider}': {e}")
            continue

    return available


@router.patch("/{repo_id}/config", response_model=dict[str, Any])
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

    # Check if a review is currently pending or running for this repo
    pr_ids_check = await db.execute(
        select(PullRequest.id).where(PullRequest.repo_id == repo.id)
    )
    existing_pr_ids = [r[0] for r in pr_ids_check.all()]
    if existing_pr_ids:
        active_rev_check = await db.execute(
            select(Review.status).where(
                Review.pr_id.in_(existing_pr_ids),
                Review.status.in_(["queued", "pending", "running"]),
            )
        )
        active_status = active_rev_check.scalars().first()
        if active_status:
            raise HTTPException(
                status_code=400,
                detail=f"Model configuration is locked while a Pull Request review is currently {active_status}. Please wait until the review completes.",
            )

    # Validate model if assigned_model and assigned_key_id are provided
    if config.assigned_provider and config.assigned_model and config.assigned_key_id:
        from app.core.security import encryption_service
        from app.services.model_discovery import model_discovery_engine
        from app.ai.discovery.engine import discovery_engine

        # Get the API key to validate access
        db_key = await api_key_service.get_by_id(db, uuid.UUID(config.assigned_key_id))
        if not db_key or not db_key.is_valid:
            raise HTTPException(status_code=400, detail="Invalid API key selected.")

        try:
            raw_key = encryption_service.decrypt(db_key.encrypted_key)
        except Exception:
            raise HTTPException(status_code=500, detail="Failed to decrypt API key.")

        # Allow deprecated assignment? Let's check if the model exists and is accessible.
        if config.assigned_provider == "openrouter":
            db_models = await discovery_engine.get_cached_models(db, config.assigned_provider)
            models = [
                {
                    "model_name": m.model_id,
                    "canonical_model_name": m.model_id,
                    "accessible": True,
                }
                for m in db_models
            ]
        else:
            models = await model_discovery_engine.get_available_models(
                config.assigned_provider, raw_key
            )
        target_model = next(
            (
                m
                for m in models
                if m["canonical_model_name"] == config.assigned_model
                or m.get("model_name") == config.assigned_model
            ),
            None,
        )

        if not target_model:
            raise HTTPException(
                status_code=400,
                detail=f"Model '{config.assigned_model}' not found in provider's available models.",
            )
        if not target_model["accessible"]:
            raise HTTPException(
                status_code=400,
                detail=f"Model '{config.assigned_model}' is currently inaccessible with your API key.",
            )

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
        "last_synced_at": (
            repo.last_synced_at.isoformat() if repo.last_synced_at else None
        ),
        "settings": repo.settings or {},
    }


# --- Repository Lifecycle Endpoints ---


@router.post("/refresh-installation", response_model=dict)
async def refresh_installation(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Refresh all repositories from GitHub App installation.

    Compares local database against GitHub and marks new/removed/updated repos.
    Preserves review history and audit logs.
    """
    try:
        result = await repository_service.refresh_installation(db, current_user.id)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to refresh installation: {e}"
        )


@router.get("/sync-runs", response_model=list[dict[str, Any]])
async def list_sync_runs(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Recent synchronization passes affecting this user (audit trail).

    Includes manual syncs triggered by the user plus the most recent
    system-wide passes (startup / background / recovery), each with its
    reason, status, and counts.
    """
    runs_result = await db.execute(
        select(SyncRun)
        .where(
            (SyncRun.triggered_by == current_user.id) | (SyncRun.triggered_by.is_(None))
        )
        .order_by(SyncRun.started_at.desc())
        .limit(limit)
    )
    runs = runs_result.scalars().all()

    return [
        {
            "id": str(run.id),
            "reason": run.reason,
            "status": run.status,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "error": run.error,
            "repo_count": run.repo_count,
            "repos_added": run.repos_added,
            "repos_updated": run.repos_updated,
            "repos_removed": run.repos_removed,
            "repos_failed": run.repos_failed,
            "prs_found": run.prs_found,
            "prs_updated": run.prs_updated,
            "jobs_enqueued": run.jobs_enqueued,
            "details": run.details,
        }
        for run in runs
    ]


@router.get("/{repo_id}/status", response_model=dict)
async def get_repository_status(
    repo_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get detailed status for a repository including GitHub state."""
    try:
        rid = uuid.UUID(repo_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid repository ID")

    try:
        result = await repository_service.get_repository_status(
            db, rid, current_user.id
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get repository status: {e}"
        )
