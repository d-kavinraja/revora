import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.github.auth import github_app_auth
from app.models.github import Installation, PullRequest, Repository
from app.models.review import Review
from app.models.sync_run import (
    SYNC_REASON_MANUAL,
    SYNC_STATUS_FAILED,
    SYNC_STATUS_PARTIAL,
    SYNC_STATUS_QUEUED,
    SYNC_STATUS_RUNNING,
    SYNC_STATUS_SUCCESS,
    SyncRun,
)
from app.models.user import User
from app.services.api_key_service import api_key_service
from app.services.repository_service import repository_service
from app.services.sync_engine import record_sync_run

# A per-repository sync is considered "in progress" while its sync_runs row
# is running and younger than this. Older running rows are treated as stale
# (process died mid-sync) — the next sync request finalizes them as failed
# and proceeds. A single-repo pass over at most 500 open PRs completes in
# single-digit minutes, so 30 minutes is a safe staleness bound.
SYNC_IN_PROGRESS_WINDOW = timedelta(minutes=30)

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

    # Durable per-repository sync state (browser-refresh safe): the latest
    # sync_runs row carrying details.repo_id. Matched in Python so the lookup
    # works on Postgres and SQLite alike. Stale running rows (> window) are
    # reported as "stale" so the UI never shows an eternal spinner after a
    # backend restart; the next sync request finalizes them.
    sync_state_by_repo: dict[str, dict[str, Any]] = {}
    try:
        runs_result = await db.execute(
            select(SyncRun).order_by(SyncRun.started_at.desc()).limit(100)
        )
        cutoff = datetime.now(UTC) - SYNC_IN_PROGRESS_WINDOW
        for run in runs_result.scalars().all():
            repo_key = _repo_run_key(run)
            if not repo_key or repo_key in sync_state_by_repo:
                continue
            status = run.status
            if status == SYNC_STATUS_RUNNING:
                started = run.started_at
                if started is not None and started.tzinfo is None:
                    started = started.replace(tzinfo=UTC)
                if started is None or started < cutoff:
                    status = "stale"
            sync_state_by_repo[repo_key] = {
                "status": status,
                "reason": run.reason,
                "started_at": (
                    run.started_at.isoformat() if run.started_at else None
                ),
                "completed_at": (
                    run.completed_at.isoformat() if run.completed_at else None
                ),
                "error": run.error,
                "prs_found": run.prs_found,
                "prs_updated": run.prs_updated,
                "jobs_enqueued": run.jobs_enqueued,
            }
    except Exception as e:
        logger.warning(f"Failed to load per-repo sync state: {e}")

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
                # Backend source of truth for sync status: survives browser
                # refresh (unlike frontend-only spinner flags). "running" →
                # sync in progress; "stale" → orphaned run, safe to re-sync.
                "sync_state": sync_state_by_repo.get(str(repo.id)),
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


def _repo_run_key(run: SyncRun) -> str | None:
    """Return the repository id a sync_runs row belongs to, if any."""
    try:
        details = run.details or {}
        return details.get("repo_id")
    except Exception:
        return None


async def _find_active_repo_sync(
    db: AsyncSession, repo_id: uuid.UUID
) -> SyncRun | None:
    """Return the in-progress (non-stale) sync_runs row for a repository.

    Matches QUEUED and RUNNING rows by details.repo_id in Python so the
    lookup works identically on Postgres and SQLite (no JSON operators).
    A QUEUED run means a sync was requested and will execute; a second
    request while queued must return "in_progress" instead of duplicating.
    """
    cutoff = datetime.now(UTC) - SYNC_IN_PROGRESS_WINDOW
    res = await db.execute(
        select(SyncRun)
        .where(SyncRun.status.in_([SYNC_STATUS_QUEUED, SYNC_STATUS_RUNNING]))
        .order_by(SyncRun.started_at.desc())
        .limit(50)
    )
    for run in res.scalars().all():
        if _repo_run_key(run) != str(repo_id):
            continue
        started = run.started_at
        if started is not None and started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if started is not None and started < cutoff:
            continue
        return run
    return None


async def _finalize_stale_repo_syncs(db: AsyncSession, repo_id: uuid.UUID) -> None:
    """Mark orphaned running sync rows for a repository as failed.

    A running row older than the in-progress window means the process died
    mid-sync (restart/crash). Best-effort: never raises.
    """
    try:
        cutoff = datetime.now(UTC) - SYNC_IN_PROGRESS_WINDOW
        res = await db.execute(
            select(SyncRun)
            .where(SyncRun.status == SYNC_STATUS_RUNNING)
            .order_by(SyncRun.started_at.desc())
            .limit(50)
        )
        for run in res.scalars().all():
            if _repo_run_key(run) != str(repo_id):
                continue
            started = run.started_at
            if started is not None and started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            if started is not None and started < cutoff:
                await record_sync_run(
                    db,
                    run.reason,
                    SYNC_STATUS_FAILED,
                    error="Sync process ended before completion (stale run).",
                    details={**(run.details or {}), "stale": True},
                    run_id=run.id,
                )
    except Exception as e:
        logger.warning(f"Failed to finalize stale sync rows for {repo_id}: {e}")


async def _background_sync_all(user_id: uuid.UUID) -> dict[str, Any]:
    """Run a full manual sync pass in the background (own DB session).

    Powers POST /sync-all and POST /refresh-installation so neither holds
    an HTTP request open past the 15s frontend timeout.
    """
    from app.db.session import AsyncSessionLocal as _SessionLocal

    try:
        async with _SessionLocal() as db:
            result = await repository_service.refresh_installation(db, user_id)
        logger.info(f"Background sync-all for user {user_id}: {result.get('status')}")
        return result
    except Exception as e:
        logger.error(f"Background sync-all failed for user {user_id}: {e}", exc_info=True)
        return {"status": "failed", "error": str(e)}


@router.post("/sync-all", response_model=dict, status_code=202)
async def sync_all_repositories(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """Start a full synchronization in the background (returns immediately).

    Delegates to the sync engine (manual reason): repositories added/updated/
    removed, PRs reconciled, missed reviews enqueued — with the same
    history-preserving semantics as the automatic recovery passes.
    Poll the repositories list (last_synced_at / last_sync) to observe
    completion; the run itself is recorded in sync_runs like every pass.
    """
    background_tasks.add_task(_background_sync_all, current_user.id)
    return {
        "status": "accepted",
        "message": "Full repository sync started in the background.",
    }


@router.post("/{repo_id}/sync", response_model=dict, status_code=202)
async def sync_repository(
    repo_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start repository synchronization in the background (returns immediately).

    PR reconciliation itself is delegated to the sync engine, which fetches
    only open PRs (paginated), reconciles closed/merged states, isolates
    per-PR failures, and enqueues reviews exclusively for eligible open PRs.
    Poll the repository's `last_synced_at` / `sync_state` to observe
    completion — the sync survives browser refresh and is never duplicated:
    a second request while a sync is running returns "in_progress".
    """
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

        # Fail fast when GitHub authentication is broken; the background
        # pass obtains its own installation token when it runs.
        try:
            await github_app_auth.get_installation_token(
                installation.installation_id
            )
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to authenticate with GitHub App: {e}"
            )

        # Duplicate-sync guard (browser refresh / double-click safe): an
        # in-progress sync owns this repository, so do not schedule another.
        await _finalize_stale_repo_syncs(db, repo.id)
        active = await _find_active_repo_sync(db, repo.id)
        if active is not None:
            return {
                "status": "in_progress",
                "message": "Repository sync is already running in the background.",
                "run_id": str(active.id),
            }

        # Durable sync state: the running row lets the UI restore the active
        # sync after a browser refresh (GET /repositories → sync_state) and
        # is finalized by the background task on success/partial/failure.
        run = await record_sync_run(
            db,
            SYNC_REASON_MANUAL,
            SYNC_STATUS_RUNNING,
            triggered_by=current_user.id,
            details={"repo_id": str(repo.id), "full_name": repo.full_name},
        )

        # The heavy PR reconciliation runs in the background so the HTTP
        # request returns immediately regardless of PR count. Actual work is
        # delegated to the sync engine (open-only, paginated, per-PR error
        # isolation) instead of duplicating a long-running loop here.
        background_tasks.add_task(
            _background_single_repo_sync, repo.id, run.id, current_user.id
        )
        return {
            "status": "accepted",
            "message": "Repository sync started in the background.",
            "run_id": str(run.id),
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error starting repository sync: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to start repository sync: {e}"
        )


async def _background_single_repo_sync(
    repo_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Reconcile one repository's PRs against GitHub (background task).

    Shares pagination, open-only review eligibility, closed/merged state
    reconciliation, per-PR error isolation, and idempotency with the
    startup/background/manual sync passes — so historically closed/merged
    PRs keep metadata-only treatment and never create Review,
    ReviewExecution, or ReviewJob rows.

    Acquires a per-repository advisory lock (pg_try_advisory_lock(hashtext(repo_id::text)))
    so this path never reconciles the same repository concurrently.
    Full installation-wide passes use a separate global lock and will skip
    repositories that are already being synced via their per-repo lock.
    Finalizes the sync_runs row created by the endpoint so the UI can
    restore/observe the sync after refresh.
    """
    from app.db.session import AsyncSessionLocal
    from app.services import sync_engine

    counts: dict[str, Any] = {
        "prs_found": 0,
        "prs_updated": 0,
        "jobs_enqueued": 0,
        "failures": {},
    }

    async def _finalize(status: str, error: str | None = None) -> None:
        if run_id is None:
            return
        try:
            async with AsyncSessionLocal() as adb:
                failures = dict(counts.get("failures", {}) or {})
                # Preserve the run's original reason (manual / webhook / login)
                # instead of overwriting it.
                reason_res = await adb.execute(
                    select(SyncRun.reason).where(SyncRun.id == run_id)
                )
                reason = reason_res.scalars().first() or SYNC_REASON_MANUAL
                await record_sync_run(
                    adb,
                    reason,
                    status,
                    counts={
                        "repo_count": 1,
                        "prs_found": counts.get("prs_found", 0),
                        "prs_updated": counts.get("prs_updated", 0),
                        "jobs_enqueued": counts.get("jobs_enqueued", 0),
                    },
                    error=error,
                    details=(
                        {**(await _run_details(adb)), "failures": failures}
                        if failures
                        else await _run_details(adb)
                    ),
                    triggered_by=user_id,
                    run_id=run_id,
                )
        except Exception as fe:
            logger.warning(f"Failed to finalize sync run {run_id}: {fe}")

    async def _run_details(adb) -> dict[str, Any]:
        try:
            res = await adb.execute(select(SyncRun).where(SyncRun.id == run_id))
            existing = res.scalars().first()
            return dict(existing.details or {}) if existing else {}
        except Exception:
            return {}

    try:
        async with AsyncSessionLocal() as db:
            # Acquire per-repository advisory lock to prevent concurrent syncs
            # of the same repository. Uses hashtext(repo_id::text) for the key.
            # If another sync for this repo is running, wait briefly then fail honestly.
            # We do NOT use the global full-pass lock; full passes will skip
            # repos with recent last_synced_at or detect contention via lock.
            repo_lock_key = f"hashtext('{repo_id}'::text)"
            locked = True
            try:
                locked = await db.scalar(
                    text(f"SELECT pg_try_advisory_lock({repo_lock_key})"),
                )
            except Exception:
                # Non-Postgres backend (tests) — proceed without lock.
                locked = True

            if not locked:
                logger.warning(
                    f"Background sync could not acquire per-repo lock for repo {repo_id}; "
                    f"another sync for this repository is in progress"
                )
                await _finalize(
                    SYNC_STATUS_FAILED,
                    error="Could not acquire per-repository synchronization lock; another sync is in progress",
                )
                return counts

            try:
                repo_res = await db.execute(
                    select(Repository).where(Repository.id == repo_id)
                )
                repo = repo_res.scalars().first()
                if (
                    not repo
                    or repo.removed_at is not None
                    or not repo.reviews_enabled
                    or repo.is_archived
                ):
                    logger.info(
                        f"Background sync skipped for repo {repo_id}: unavailable"
                    )
                    await _finalize(SYNC_STATUS_SUCCESS)
                    return counts
                inst_res = await db.execute(
                    select(Installation).where(Installation.id == repo.installation_id)
                )
                inst = inst_res.scalars().first()
                if not inst or not inst.permissions_ok:
                    logger.info(
                        f"Background sync skipped for repo {repo_id}: installation not ready"
                    )
                    await _finalize(SYNC_STATUS_SUCCESS)
                    return counts

                headers = {
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                }
                now = datetime.now(UTC)
                prs_found, prs_updated, jobs_enqueued = (
                    await sync_engine._sync_repository_prs(
                        db, repo, inst, headers, counts, now
                    )
                )
                counts["prs_found"] += prs_found
                counts["prs_updated"] += prs_updated
                counts["jobs_enqueued"] += jobs_enqueued
                repo.last_synced_at = now
                db.add(repo)
                await db.commit()
                logger.info(
                    f"Background sync for {repo.full_name}: {prs_found} open PR(s), "
                    f"{jobs_enqueued} job(s) enqueued, "
                    f"{len(counts['failures'])} failure(s)"
                )
                await _finalize(
                    SYNC_STATUS_PARTIAL if counts["failures"] else SYNC_STATUS_SUCCESS,
                    error=(
                        "; ".join(
                            f"{k}: {v}"
                            for k, v in list(counts["failures"].items())[:5]
                        )
                        or None
                    ),
                )
            finally:
                try:
                    await db.execute(
                        text(f"SELECT pg_advisory_unlock({repo_lock_key})"),
                    )
                except Exception:
                    pass
    except Exception as e:
        logger.error(
            f"Background repository sync failed for {repo_id}: {e}", exc_info=True
        )
        counts["failures"][str(repo_id)] = f"{type(e).__name__}: {e}"
        await _finalize(SYNC_STATUS_FAILED, error=str(e))
    return counts


async def _background_single_repo_sync_with_retry(
    repo_id: uuid.UUID,
    run_id: uuid.UUID,
    user_id: uuid.UUID | None,
    max_retries: int = 3,
) -> None:
    """Execute background sync with retry on lock contention.

    If the per-repo lock is unavailable (another sync for this repo is running),
    wait with exponential backoff and retry. After max_retries, finalize as FAILED.
    """
    from app.db.session import AsyncSessionLocal as _SessionLocal

    for attempt in range(max_retries):
        try:
            await _background_single_repo_sync(repo_id, run_id, user_id)
            return  # Success
        except Exception as e:
            # Check if it's a lock contention error by checking the sync run status
            async with _SessionLocal() as db:
                run = await db.execute(select(SyncRun).where(SyncRun.id == run_id))
                run = run.scalars().first()
                if run and run.status == SYNC_STATUS_FAILED:
                    # Already finalized as failed by _background_single_repo_sync
                    return

            if attempt == max_retries - 1:
                # Final attempt failed - finalize as FAILED
                logger.error(
                    f"Background sync for repo {repo_id} failed after {max_retries} retries: {e}"
                )
                async with _SessionLocal() as db:
                    await record_sync_run(
                        db,
                        SYNC_REASON_MANUAL,
                        SYNC_STATUS_FAILED,
                        error=f"Max retries exceeded: {e}",
                        run_id=run_id,
                    )
                return
            # Exponential backoff
            await asyncio.sleep(2 ** attempt)


async def _process_queued_sync(run_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
    """Pick up a QUEUED sync run, transition to RUNNING, and execute with retries.

    This replaces the fire-and-forget asyncio.create_task pattern with a
    durable queue backed by sync_runs. The QUEUED run survives backend restarts
    and is picked up by startup recovery.
    """
    from app.db.session import AsyncSessionLocal as _SessionLocal2

    async with _SessionLocal2() as db:
        run = await db.execute(select(SyncRun).where(SyncRun.id == run_id))
        run = run.scalars().first()
        if not run or run.status != SYNC_STATUS_QUEUED:
            return  # Already picked up, cancelled, or not queued

        repo_id = uuid.UUID(run.details["repo_id"])

        # Transition to RUNNING
        await record_sync_run(db, run.reason, SYNC_STATUS_RUNNING, run_id=run_id)

    # Execute with retry logic (handles lock contention)
    await _background_single_repo_sync_with_retry(repo_id, run_id, user_id)


# --- GitHub Stats Proxy ---


@router.get("/{repo_id}/github-stats", response_model=dict[str, Any])
async def get_repo_github_stats(
    repo_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch live GitHub stats (stars, forks, issues, contributors, avatar) for a repository.

    This proxies the GitHub API request using the secure installation token
    so the frontend never needs a personal access token.
    """
    try:
        rid = uuid.UUID(repo_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid repository ID")

    # Verify the repo belongs to this user
    installations_result = await db.execute(
        select(Installation).where(Installation.user_id == current_user.id)
    )
    installations = installations_result.scalars().all()
    installation_ids = [i.id for i in installations]

    repo_result = await db.execute(
        select(Repository).where(
            Repository.id == rid,
            Repository.installation_id.in_(installation_ids),
        )
    )
    repo = repo_result.scalars().first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    inst = next((i for i in installations if i.id == repo.installation_id), None)
    if not inst:
        raise HTTPException(status_code=404, detail="Installation not found")

    parts = repo.full_name.split("/")
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="Invalid repository full name format.")
    owner, repo_name = parts

    try:
        token = await github_app_auth.get_installation_token(inst.installation_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to authenticate with GitHub App: {e}")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Fetch main repo data
        repo_res = await client.get(
            f"https://api.github.com/repos/{owner}/{repo_name}",
            headers=headers,
        )
        if not repo_res.is_success:
            raise HTTPException(status_code=502, detail="Failed to fetch repository data from GitHub.")

        gh_data = repo_res.json()

        # Fetch contributor count using pagination trick (HEAD with per_page=1 then parse Link header)
        contrib_res = await client.get(
            f"https://api.github.com/repos/{owner}/{repo_name}/contributors?per_page=1&anon=true",
            headers=headers,
        )
        contributors = 0
        if contrib_res.is_success:
            link_header = contrib_res.headers.get("link", "")
            if 'rel="last"' in link_header:
                # Extract page number from link header: ...<url?page=N>; rel="last"
                import re
                match = re.search(r'[?&]page=(\d+)[^>]*>;\s*rel="last"', link_header)
                if match:
                    contributors = int(match.group(1))
            else:
                # If there's no "last" link, all contributors fit on one page
                contrib_list = contrib_res.json()
                if isinstance(contrib_list, list):
                    contributors = len(contrib_list)

        return {
            "stars": gh_data.get("stargazers_count", 0),
            "forks": gh_data.get("forks_count", 0),
            "open_issues": gh_data.get("open_issues_count", 0),
            "contributors": contributors,
            "owner_avatar_url": gh_data.get("owner", {}).get("avatar_url", None),
            "homepage": gh_data.get("homepage") or None,
            "topics": gh_data.get("topics", []),
            "watchers": gh_data.get("watchers_count", 0),
        }


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

    from app.ai.discovery.engine import discovery_engine
    from app.core.security import encryption_service
    from app.services.model_discovery import model_discovery_engine

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
        from app.ai.discovery.engine import discovery_engine
        from app.core.security import encryption_service
        from app.services.model_discovery import model_discovery_engine

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
            try:
                models = await model_discovery_engine.get_available_models(
                    config.assigned_provider, raw_key
                )
            except Exception:
                # Discovery now raises typed errors (auth/busy/unavailable)
                # instead of returning []. Surface as 400 so model assignment
                # validation keeps its previous user-facing contract.
                raise HTTPException(
                    status_code=400,
                    detail=f"Model '{config.assigned_model}' could not be verified with the selected API key.",
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


@router.post("/refresh-installation", response_model=dict, status_code=202)
async def refresh_installation(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """Refresh all repositories from GitHub App installation (background).

    Same background full sync as POST /sync-all: compares local database
    against GitHub and marks new/removed/updated repos. Preserves review
    history and audit logs. Returns immediately to stay under the frontend
    HTTP timeout.
    """
    background_tasks.add_task(_background_sync_all, current_user.id)
    return {
        "status": "accepted",
        "message": "Installation refresh started in the background.",
    }


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
