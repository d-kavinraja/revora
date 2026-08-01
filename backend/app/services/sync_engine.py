"""Sync engine — automatic recovery and repository synchronization.

Brings the local DB back in line with GitHub after server downtime (or any
missed webhook): repositories (new / removed / renamed / archived / permission
changes), pull requests (new / reopened / closed / merged / new commits) and
missed review enqueueing.

Concurrency rules (documented behavior — see also queue/dispatcher.py):
1. Webhooks always win for freshness. A webhook-triggered job for a newer
   head_sha supersedes any sync-triggered job (dispatcher.supersede_jobs).
2. Sync/recovery skips work that is already processed:
   - an active (queued/pending/running) review already exists for the PR;
   - a ReviewExecution already exists for (PR, commit_sha) — this prevents a
     duplicate review when a webhook already reviewed the same commit.
3. Idempotency remains the safety net: ReviewJob has a UNIQUE constraint on
   (delivery_id, head_sha) with INSERT ... ON CONFLICT DO NOTHING, and the
   dispatcher refuses to create a second active review per PR.
4. The background loop holds a Postgres advisory lock so multiple API workers
   never run the same pass concurrently.

Sync reasons recorded on every sync_runs row: startup / background / manual /
webhook / recovery.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import select, text

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.github import Installation, Repository, PullRequest
from app.models.review import Review
from app.models.execution import ReviewExecution
from app.models.sync_run import (
    SyncRun,
    SYNC_REASON_BACKGROUND,
    SYNC_REASON_MANUAL,
    SYNC_REASON_RECOVERY,
    SYNC_REASON_STARTUP,
    SYNC_REASON_WEBHOOK,
    SYNC_STATUS_FAILED,
    SYNC_STATUS_PARTIAL,
    SYNC_STATUS_RUNNING,
    SYNC_STATUS_SUCCESS,
)
from app.github.auth import github_app_auth

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
_SYNC_ADVISORY_LOCK_KEY = 0x5A9C1024
_ACTIVE_REVIEW_STATUSES = ("queued", "pending", "running")

# Minimum GitHub App permissions Revora needs to review a repository.
# (The issues permission is NOT required — installations granted only
# pull_requests/checks/contents must never be gated.)
REQUIRED_PERMISSIONS: Dict[str, str] = {
    "pull_requests": "write",
    "checks": "write",
    "contents": "read",
}
_PERMISSION_LEVELS = {"none": 0, "read": 1, "write": 2, "admin": 3}


def sync_delivery_id(repo_github_id: int, pr_number: int, head_sha: str) -> str:
    """Deterministic delivery id — idempotent across runs, workers, and
    overlapping webhook processing (ReviewJob is unique on delivery_id+sha)."""
    return f"sync:{repo_github_id}:{pr_number}:{head_sha}"


def _has_required_permissions(permissions: Optional[Dict[str, Any]], suspended_at) -> bool:
    """True while the installation still has every permission Revora needs."""
    if suspended_at is not None:
        return False
    if not permissions:
        # Unknown permission set — never gate on missing data.
        return True
    for perm, required_level in REQUIRED_PERMISSIONS.items():
        granted = _PERMISSION_LEVELS.get(str(permissions.get(perm, "none")).lower(), 0)
        if granted < _PERMISSION_LEVELS[required_level]:
            return False
    return True


def _ensure_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize naive datetimes (SQLite returns naive) to UTC-aware."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# sync_runs bookkeeping
# ---------------------------------------------------------------------------

async def record_sync_run(
    db,
    reason: str,
    status: str,
    counts: Optional[Dict[str, int]] = None,
    error: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    triggered_by: Optional[uuid.UUID] = None,
    run_id: Optional[uuid.UUID] = None,
) -> SyncRun:
    """Create (or finalize, when run_id is given) a sync_runs audit row.

    Best-effort: never raises — callers (startup recovery, passes) must not
    fail because audit recording failed.
    """
    counts = counts or {}
    try:
        run = None
        if run_id:
            res = await db.execute(select(SyncRun).where(SyncRun.id == run_id))
            run = res.scalars().first()
        if run is None:
            run = SyncRun(
                reason=reason,
                triggered_by=triggered_by,
                started_at=datetime.now(timezone.utc),
                status=SYNC_STATUS_RUNNING,
            )
            db.add(run)
        else:
            run.status = status
            run.completed_at = datetime.now(timezone.utc)
            run.error = error
            run.repo_count = counts.get("repo_count", 0)
            run.repos_added = counts.get("repos_added", 0)
            run.repos_updated = counts.get("repos_updated", 0)
            run.repos_removed = counts.get("repos_removed", 0)
            run.repos_failed = counts.get("repos_failed", 0)
            run.prs_found = counts.get("prs_found", 0)
            run.prs_updated = counts.get("prs_updated", 0)
            run.jobs_enqueued = counts.get("jobs_enqueued", 0)
            run.details = details if details else None
        await db.commit()
        await db.refresh(run)
        return run
    except Exception as e:
        logger.warning(f"Failed to record sync run ({reason}/{status}): {e}")
        raise


# ---------------------------------------------------------------------------
# Repository-level pass
# ---------------------------------------------------------------------------

async def sync_repositories_once(
    reason: str,
    user_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Add/update/mark-removed repositories and refresh installation
    permissions for every installation (or a single user).

    Each repository is handled independently — one failing installation
    never aborts the pass. Removed repositories are marked (removed_at) and
    unlinked, NEVER deleted, so all review history is preserved.

    Returns counts plus a per-repo failure map.
    """
    now = datetime.now(timezone.utc)
    counts: Dict[str, Any] = {
        "repo_count": 0,
        "repos_added": 0,
        "repos_updated": 0,
        "repos_removed": 0,
        "repos_failed": 0,
        "failures": {},
    }
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with AsyncSessionLocal() as db:
        q = select(Installation)
        if user_id:
            q = q.where(Installation.user_id == user_id)
        installations = (await db.execute(q)).scalars().all()

        for inst in installations:
            inst_started_at = now
            inst_ok = True
            inst_error: Optional[str] = None
            try:
                token = await github_app_auth.get_installation_token(inst.installation_id)
                auth_headers = {**headers, "Authorization": f"Bearer {token}"}

                async with httpx.AsyncClient() as client:
                    repos_res = await client.get(
                        f"{GITHUB_API}/installation/repositories",
                        headers=auth_headers,
                    )
                    if not repos_res.is_success:
                        raise RuntimeError(
                            f"GitHub repo list failed: {repos_res.status_code} "
                            f"{repos_res.text[:300]}"
                        )
                    gh_repos = repos_res.json().get("repositories", [])

                    gh_ids = set()
                    for r in gh_repos:
                        gh_id = r.get("id")
                        if not gh_id:
                            continue
                        gh_ids.add(gh_id)
                        counts["repo_count"] += 1
                        try:
                            res = await db.execute(
                                select(Repository).where(Repository.github_id == gh_id)
                            )
                            db_repo = res.scalars().first()

                            if db_repo is None:
                                db_repo = Repository(
                                    github_id=gh_id,
                                    name=r.get("name") or "",
                                    full_name=r.get("full_name") or "",
                                    description=r.get("description"),
                                    language=r.get("language"),
                                    is_private=bool(r.get("private", False)),
                                    installation_id=inst.id,
                                    reviews_enabled=True,
                                    is_archived=bool(r.get("archived", False)),
                                    last_synced_at=now,
                                )
                                db.add(db_repo)
                                counts["repos_added"] += 1
                                logger.info(f"[sync:{reason}] New repository: {db_repo.full_name}")
                            else:
                                changed = False
                                for attr, key in (
                                    ("name", "name"),
                                    ("full_name", "full_name"),
                                    ("description", "description"),
                                    ("language", "language"),
                                    ("is_private", "private"),
                                ):
                                    new_val = r.get(key)
                                    if new_val is not None and getattr(db_repo, attr) != new_val:
                                        setattr(db_repo, attr, new_val)
                                        changed = True
                                gh_archived = bool(r.get("archived", False))
                                if db_repo.is_archived != gh_archived:
                                    db_repo.is_archived = gh_archived
                                    changed = True

                                # User intent (reviews_enabled) is preserved on
                                # metadata refreshes — only flipped on explicit
                                # re-add or removal.
                                if db_repo.removed_at is not None:
                                    db_repo.removed_at = None
                                    db_repo.reviews_enabled = True
                                    changed = True
                                    logger.info(
                                        f"[sync:{reason}] Repository re-added: {db_repo.full_name}"
                                    )
                                db_repo.installation_id = inst.id
                                db_repo.last_synced_at = now
                                if changed:
                                    counts["repos_updated"] += 1
                        except Exception as e:
                            full_name = r.get("full_name") or str(gh_id)
                            counts["failures"][full_name] = f"{type(e).__name__}: {e}"
                            logger.error(f"[sync:{reason}] Repo upsert failed for {full_name}: {e}", exc_info=True)

                    # Mark removed — only when the fetched list is non-empty to
                    # avoid mass-removal on a transient API glitch.
                    if gh_ids:
                        stale_res = await db.execute(
                            select(Repository).where(
                                Repository.installation_id == inst.id,
                                Repository.github_id.not_in(list(gh_ids)),
                            )
                        )
                        for stale in stale_res.scalars().all():
                            if stale.removed_at is None:
                                stale.removed_at = now
                                stale.installation_id = None
                                stale.reviews_enabled = False
                                db.add(stale)
                                counts["repos_removed"] += 1
                                counts["failures"].pop(stale.full_name, None)
                                logger.info(
                                    f"[sync:{reason}] Repository removed from installation: {stale.full_name}"
                                )

                # Permission refresh (best-effort — never fails the pass).
                try:
                    gh_inst = await github_app_auth.get_installation(inst.installation_id)
                    if gh_inst is None:
                        # Installation vanished on GitHub (uninstall missed by
                        # webhooks) — unlink everything under it.
                        inst.permissions_ok = False
                        inst.suspended_at = now
                        orphan_res = await db.execute(
                            select(Repository).where(Repository.installation_id == inst.id)
                        )
                        for orphan in orphan_res.scalars().all():
                            if orphan.removed_at is None:
                                orphan.removed_at = now
                                orphan.installation_id = None
                                orphan.reviews_enabled = False
                                counts["repos_removed"] += 1
                        logger.warning(
                            f"[sync:{reason}] Installation {inst.installation_id} no longer "
                            f"exists on GitHub — unlinked its repositories"
                        )
                    else:
                        gh_perms = gh_inst.get("permissions") or {}
                        if gh_perms:
                            inst.permissions = gh_perms
                        suspended = gh_inst.get("suspended_at")
                        inst.suspended_at = (
                            datetime.fromisoformat(str(suspended).replace("Z", "+00:00"))
                            if suspended
                            else None
                        )
                        inst.permissions_ok = _has_required_permissions(inst.permissions, inst.suspended_at)
                        if not inst.permissions_ok:
                            logger.warning(
                                f"[sync:{reason}] Installation {inst.installation_id} is "
                                f"missing required permissions or is suspended — reviews gated"
                            )
                except Exception as e:
                    logger.warning(
                        f"[sync:{reason}] Permission refresh failed for installation "
                        f"{inst.installation_id}: {e}"
                    )
            except Exception as e:
                inst_ok = False
                inst_error = f"{type(e).__name__}: {e}"
                counts["failures"][f"installation:{inst.installation_id}"] = inst_error
                logger.error(
                    f"[sync:{reason}] Installation {inst.installation_id} failed: {e}",
                    exc_info=True,
                )

            # Per-installation last-sync markers (UI: "Last synchronized X ago").
            inst.last_sync_started_at = inst_started_at
            inst.last_sync_completed_at = datetime.now(timezone.utc)
            inst.last_sync_status = "success" if inst_ok else "failed"
            inst.last_sync_error = inst_error
            inst.last_sync_reason = reason
            db.add(inst)

        await db.commit()

    counts["repos_failed"] = len(counts["failures"])
    return counts


# ---------------------------------------------------------------------------
# PR-level pass
# ---------------------------------------------------------------------------

async def sync_prs_once(
    reason: str,
    user_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Reconcile open PRs (new / new commit / reopened / closed) for active
    repositories and enqueue missed reviews.

    Tiered scope (background): repos with open PRs sync every
    SYNC_RECOVERY_INTERVAL_MINUTES, recently-updated repos every
    SYNC_TIER2_INTERVAL_MINUTES, the rest every SYNC_TIER3_INTERVAL_MINUTES.
    Startup and manual passes sync everything.

    Returns counts plus a per-repo failure map.
    """
    now = datetime.now(timezone.utc)
    counts: Dict[str, Any] = {
        "prs_found": 0,
        "prs_updated": 0,
        "jobs_enqueued": 0,
        "failures": {},
    }
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    tier1_min = settings.SYNC_RECOVERY_INTERVAL_MINUTES
    tier2_min = settings.SYNC_TIER2_INTERVAL_MINUTES
    tier3_min = settings.SYNC_TIER3_INTERVAL_MINUTES
    active_days = settings.SYNC_TIER2_ACTIVE_DAYS
    full_pass = reason in (SYNC_REASON_STARTUP, SYNC_REASON_MANUAL)

    async with AsyncSessionLocal() as db:
        # Active repos: linked, not removed, reviews enabled, not archived,
        # under an installation with the required permissions.
        q = (
            select(Repository, Installation)
            .join(Installation, Repository.installation_id == Installation.id)
            .where(
                Repository.installation_id.isnot(None),
                Repository.removed_at.is_(None),
                Repository.reviews_enabled.is_(True),
                Repository.is_archived.is_(False),
                Installation.permissions_ok.is_(True),
            )
        )
        if user_id:
            q = q.where(Installation.user_id == user_id)
        rows = (await db.execute(q)).all()

        # Repos that locally have open/draft PRs (tier 1 signal + priority).
        open_pr_repo_ids = set(
            (
                await db.execute(
                    select(PullRequest.repo_id).where(
                        PullRequest.status.in_(["open", "draft"])
                    )
                )
            ).scalars().all()
        )

        due_repos: List[tuple[Repository, Installation]] = []
        for repo, inst in rows:
            last = _ensure_aware(repo.last_synced_at)
            has_open = repo.id in open_pr_repo_ids
            if full_pass or last is None:
                due = True
            elif has_open:
                due = tier1_min > 0 and (now - last) >= timedelta(minutes=tier1_min)
            elif (now - last) <= timedelta(days=active_days):
                due = tier2_min > 0 and (now - last) >= timedelta(minutes=tier2_min)
            else:
                due = tier3_min <= 0 or (now - last) >= timedelta(minutes=tier3_min)
            if due:
                due_repos.append((repo, inst))

        # Priority: repos with open PRs first, then never-synced, then oldest.
        due_repos.sort(
            key=lambda ri: (
                ri[0].id not in open_pr_repo_ids,
                ri[0].last_synced_at is not None,
                _ensure_aware(ri[0].last_synced_at) or datetime.min.replace(tzinfo=timezone.utc),
            )
        )

        for repo, inst in due_repos:
            try:
                prs_found, prs_updated, jobs_enqueued = await _sync_repository_prs(
                    db, repo, inst, headers, counts, now
                )
                counts["prs_found"] += prs_found
                counts["prs_updated"] += prs_updated
                counts["jobs_enqueued"] += jobs_enqueued
                repo.last_synced_at = now
                db.add(repo)
            except Exception as e:
                counts["failures"][repo.full_name] = f"{type(e).__name__}: {e}"
                logger.error(
                    f"[sync:{reason}] PR sync failed for {repo.full_name}: {e}",
                    exc_info=True,
                )

        await db.commit()

    return counts


async def _sync_repository_prs(
    db,
    repo: Repository,
    inst: Installation,
    headers: Dict[str, str],
    counts: Dict[str, Any],
    now: datetime,
) -> tuple[int, int, int]:
    """Fetch open PRs for one repository and reconcile each against the DB.

    Per-PR isolation: a failure on one PR is logged and skipped, never
    propagated — one bad PR cannot abort the repository.
    """
    owner, repo_name = repo.full_name.split("/", 1)
    token = await github_app_auth.get_installation_token(inst.installation_id)
    auth_headers = {**headers, "Authorization": f"Bearer {token}"}

    gh_open: List[dict] = []
    async with httpx.AsyncClient() as client:
        page = 1
        while True:
            res = await client.get(
                f"{GITHUB_API}/repos/{owner}/{repo_name}/pulls",
                params={"state": "open", "per_page": 100, "page": page},
                headers=auth_headers,
            )
            if res.status_code in (403, 429):
                raise RuntimeError(f"GitHub rate limit exceeded: {res.status_code}")
            if res.status_code == 404:
                # Repo deleted/renamed on GitHub — repo pass will unlink it.
                return 0, 0, 0
            if not res.is_success:
                raise RuntimeError(f"PR list failed: {res.status_code} {res.text[:200]}")
            batch = res.json()
            gh_open.extend(batch)
            if len(batch) < 100 or page >= 5:
                break
            page += 1

        prs_found = 0
        prs_updated = 0
        jobs_enqueued = 0
        open_numbers: set[int] = set()

        for gh_pr in gh_open:
            pr_number = int(gh_pr.get("number", 0))
            if not pr_number:
                continue
            open_numbers.add(pr_number)
            prs_found += 1
            try:
                action, updated = await _reconcile_single_pr(
                    db, repo, inst, owner, repo_name, gh_pr, auth_headers
                )
                if action == "enqueued":
                    jobs_enqueued += 1
                elif updated:
                    prs_updated += 1
            except Exception as e:
                counts["failures"][f"{repo.full_name}#{pr_number}"] = f"{type(e).__name__}: {e}"
                logger.error(
                    f"[sync] PR #{pr_number} of {repo.full_name} failed: {e}",
                    exc_info=True,
                )

        # Reconcile locally-open PRs that GitHub no longer lists as open.
        local_res = await db.execute(
            select(PullRequest).where(
                PullRequest.repo_id == repo.id,
                PullRequest.status.in_(["open", "draft"]),
            )
        )
        for db_pr in local_res.scalars().all():
            if db_pr.pr_number in open_numbers:
                continue
            try:
                gh_res = await client.get(
                    f"{GITHUB_API}/repos/{owner}/{repo_name}/pulls/{db_pr.pr_number}",
                    headers=auth_headers,
                )
                new_status = None
                if gh_res.is_success:
                    gh_pr = gh_res.json()
                    if bool(gh_pr.get("merged", False)):
                        new_status = "merged"
                    elif gh_pr.get("state") == "closed":
                        new_status = "closed"
                elif gh_res.status_code == 404:
                    new_status = "closed"
                if new_status and db_pr.status != new_status:
                    db_pr.status = new_status
                    db.add(db_pr)
                    prs_updated += 1
                    logger.info(f"[sync] PR #{db_pr.pr_number} of {repo.full_name} -> {new_status}")
            except Exception as e:
                counts["failures"][f"{repo.full_name}#{db_pr.pr_number}"] = f"{type(e).__name__}: {e}"
                logger.error(
                    f"[sync] Close-reconcile failed for {repo.full_name}#{db_pr.pr_number}: {e}",
                    exc_info=True,
                )

    return prs_found, prs_updated, jobs_enqueued


async def _reconcile_single_pr(
    db,
    repo: Repository,
    inst: Installation,
    owner: str,
    repo_name: str,
    gh_pr: dict,
    auth_headers: Dict[str, str],
) -> tuple[str, bool]:
    """Reconcile one PR row with GitHub state; enqueue a review when missed.

    Returns (action, updated):
      action  — "enqueued" | "skipped" | "noop" | "updated"
      updated — True when the PR row (or a closed state) changed.
    """
    pr_number = int(gh_pr["number"])
    head_sha = gh_pr["head"]["sha"]
    title = gh_pr.get("title", "")
    author = (gh_pr.get("user") or {}).get("login", "")
    base_branch = (gh_pr.get("base") or {}).get("ref", "")
    head_branch = (gh_pr.get("head") or {}).get("ref", "")
    draft = bool(gh_pr.get("draft", False))

    res = await db.execute(
        select(PullRequest).where(
            PullRequest.repo_id == repo.id,
            PullRequest.pr_number == pr_number,
        )
    )
    db_pr = res.scalars().first()

    updated = False
    if db_pr is None:
        db_pr = PullRequest(
            repo_id=repo.id,
            pr_number=pr_number,
            title=title,
            author=author,
            head_sha=head_sha,
            base_branch=base_branch,
            head_branch=head_branch,
            status="draft" if draft else "open",
            additions=gh_pr.get("additions", 0),
            deletions=gh_pr.get("deletions", 0),
            changed_files=gh_pr.get("changed_files", 0),
        )
        db.add(db_pr)
        await db.flush()
        updated = True
        webhook_action = "opened"
    else:
        same_sha = db_pr.head_sha == head_sha
        was_closed = db_pr.status in ("closed", "merged")
        # Reopened (or first sync after a missed reopened webhook) → new review.
        if was_closed:
            db_pr.status = "draft" if draft else "open"
            updated = True
            webhook_action = "opened"
        elif not same_sha:
            db_pr.head_sha = head_sha
            db_pr.title = title
            db_pr.author = author
            db_pr.base_branch = base_branch
            db_pr.head_branch = head_branch
            updated = True
            webhook_action = "synchronize"
        else:
            if db_pr.title != title or db_pr.author != author:
                db_pr.title = title
                db_pr.author = author
                updated = True
            return "noop", updated
        db.add(db_pr)
        await db.flush()

    # --- Guards: skip work that is already processed (rule 2) ----------------
    if await _execution_exists_for_sha(db, db_pr.id, head_sha):
        logger.info(f"[sync] PR #{pr_number} already reviewed at {head_sha[:12]} — skipped")
        return "skipped", updated

    active = (
        await db.execute(
            select(Review.id)
            .where(Review.pr_id == db_pr.id, Review.status.in_(_ACTIVE_REVIEW_STATUSES))
            .limit(1)
        )
    ).scalars().first()
    if active is not None and webhook_action == "opened":
        logger.info(f"[sync] Active review exists for PR #{pr_number} — skipped")
        return "skipped", updated

    # Fetch PR detail (additions/deletions) only when we are about to enqueue.
    additions, deletions, changed_files = 0, 0, 0
    async with httpx.AsyncClient() as client:
        detail_res = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo_name}/pulls/{pr_number}",
            headers=auth_headers,
        )
        if detail_res.is_success:
            d = detail_res.json()
            additions = d.get("additions", 0)
            deletions = d.get("deletions", 0)
            changed_files = d.get("changed_files", 0)

    payload = {
        "installation": {"id": inst.installation_id},
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

    from app.queue.dispatcher import enqueue_review_job

    job = await enqueue_review_job(
        db,
        payload,
        sync_delivery_id(repo.github_id, pr_number, head_sha),
        webhook_action=webhook_action,
    )
    if job:
        logger.info(
            f"[sync] Enqueued missed review for PR #{pr_number} of {repo.full_name} "
            f"(action={webhook_action}, sha={head_sha[:12]})"
        )
        return "enqueued", updated
    return "skipped", updated


async def _execution_exists_for_sha(db, pr_id: uuid.UUID, head_sha: str) -> bool:
    """True when this PR already has an execution on this exact commit.

    Guards against duplicate reviews when a webhook already processed the
    same head_sha (different delivery_id would otherwise bypass ON CONFLICT).
    """
    res = await db.execute(
        select(ReviewExecution.id)
        .join(Review, ReviewExecution.review_id == Review.id)
        .where(Review.pr_id == pr_id, ReviewExecution.commit_sha == head_sha)
        .limit(1)
    )
    return res.scalars().first() is not None


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

async def run_sync_pass(
    reason: str,
    user_id: Optional[uuid.UUID] = None,
    use_advisory_lock: bool = True,
) -> Dict[str, Any]:
    """Full pass: repository sync + PR sync, with a sync_runs audit row.

    Returns a summary dict. Raises on catastrophic failure (after recording
    the failed run).
    """
    if use_advisory_lock:
        return await _run_sync_pass_locked(reason, user_id)
    return await _run_sync_pass(reason, user_id)


async def _run_sync_pass_locked(reason: str, user_id: Optional[uuid.UUID]) -> Dict[str, Any]:
    """Hold a Postgres advisory lock for the whole pass so multiple API
    workers never run the same pass concurrently (rule 4).

    Falls back to an unlocked pass when the database does not support
    advisory locks (e.g. SQLite test databases).
    """
    async with AsyncSessionLocal() as lock_db:
        try:
            locked = await lock_db.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": _SYNC_ADVISORY_LOCK_KEY}
            )
        except Exception:
            # Non-Postgres backend (tests) — run without the lock.
            return await _run_sync_pass(reason, user_id)
        if not locked:
            logger.info("Sync pass skipped — another worker holds the advisory lock")
            return {"status": "skipped", "reason": "advisory_lock"}
        try:
            return await _run_sync_pass(reason, user_id)
        finally:
            await lock_db.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": _SYNC_ADVISORY_LOCK_KEY}
            )


async def _run_sync_pass(reason: str, user_id: Optional[uuid.UUID]) -> Dict[str, Any]:
    run_id: Optional[uuid.UUID] = None
    async with AsyncSessionLocal() as db:
        run = await record_sync_run(db, reason, SYNC_STATUS_RUNNING, triggered_by=user_id)
        run_id = run.id

    try:
        repo_counts = await sync_repositories_once(reason, user_id=user_id)
        pr_counts = await sync_prs_once(reason, user_id=user_id)
        counts = {**repo_counts, **pr_counts}
        counts.pop("failures", None)
        failures = {**repo_counts.get("failures", {}), **pr_counts.get("failures", {})}
        repo_counts.pop("failures", None)
        pr_counts.pop("failures", None)

        status = SYNC_STATUS_PARTIAL if failures else SYNC_STATUS_SUCCESS
        error = "; ".join(f"{k}: {v}" for k, v in list(failures.items())[:5]) or None
        async with AsyncSessionLocal() as db:
            await record_sync_run(
                db, reason, status,
                counts=counts,
                error=error,
                details=failures or None,
                triggered_by=user_id,
                run_id=run_id,
            )
        logger.info(
            f"Sync pass [{reason}] finished as {status}: "
            f"{counts.get('repos_added', 0)} repos added, "
            f"{counts.get('repos_removed', 0)} removed, "
            f"{counts.get('jobs_enqueued', 0)} reviews enqueued, "
            f"{len(failures)} failures"
        )
        return {"status": status, "counts": counts, "failures": failures}
    except Exception as e:
        logger.error(f"Sync pass [{reason}] failed: {e}", exc_info=True)
        try:
            async with AsyncSessionLocal() as db:
                await record_sync_run(
                    db, reason, SYNC_STATUS_FAILED,
                    error=str(e),
                    triggered_by=user_id,
                    run_id=run_id,
                )
        except Exception:
            pass
        raise


# ---------------------------------------------------------------------------
# Background loop
# ---------------------------------------------------------------------------

async def sync_loop() -> None:
    """Background tiered sync loop (replaces pr_state_sync_loop).

    Every SYNC_RECOVERY_INTERVAL_MINUTES the pass runs; repos are only
    touched when due per their tier, keeping GitHub API usage proportional
    to activity.
    """
    if settings.SYNC_RECOVERY_INTERVAL_MINUTES <= 0:
        logger.info("Sync loop disabled (SYNC_RECOVERY_INTERVAL_MINUTES=0)")
        return
    logger.info(
        f"Sync loop started (tier1={settings.SYNC_RECOVERY_INTERVAL_MINUTES}m, "
        f"tier2={settings.SYNC_TIER2_INTERVAL_MINUTES}m, tier3={settings.SYNC_TIER3_INTERVAL_MINUTES}m)"
    )
    while True:
        try:
            await run_sync_pass(SYNC_REASON_BACKGROUND)
        except Exception as e:
            logger.error(f"Background sync failed: {e}", exc_info=True)
        await asyncio.sleep(settings.SYNC_RECOVERY_INTERVAL_MINUTES * 60)
