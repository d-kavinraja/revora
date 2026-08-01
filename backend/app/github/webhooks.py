import hmac
import hashlib
import asyncio
import httpx
import uuid
from datetime import datetime, timezone
from typing import Dict, Any
from sqlalchemy import select

import hmac
import hashlib
import asyncio
import httpx
import uuid
from datetime import datetime, timezone
from typing import Dict, Any
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.github import Installation, Repository, PullRequest
from app.models.review import Review
from app.models.user import User
from app.github.auth import github_app_auth
from app.github.client import github_client
from app.github.shared import resolve_provider_config, get_or_create_review_records, record_usage_stats
from app.services.github_service import github_service
from app.services.sync_engine import _has_required_permissions


async def handle_installation_created(payload: Dict[str, Any], delivery_id: str):
    print(f"[{delivery_id}] Handling installation.created event...")
    installation_payload = payload.get("installation", {})
    inst_id = installation_payload.get("id")
    account = installation_payload.get("account", {})
    account_id = account.get("id")
    account_login = account.get("login")
    account_type = account.get("type")
    repository_selection = installation_payload.get("repository_selection")
    permissions = installation_payload.get("permissions", {})
    events = installation_payload.get("events", [])

    sender = payload.get("sender", {})
    sender_github_id = sender.get("id")
    sender_login = sender.get("login")

    async with AsyncSessionLocal() as db:
        user = None
        if sender_github_id:
            result = await db.execute(select(User).where(User.github_id == sender_github_id))
            user = result.scalars().first()
        if not user and sender_login:
            result = await db.execute(select(User).where(User.github_username == sender_login))
            user = result.scalars().first()

        if not user:
            print(
                f"[{delivery_id}] Sender '{sender_login}' (github_id={sender_github_id}) "
                f"is not a registered Revora user. Installation {inst_id} will not be linked."
            )
            return

        res = await db.execute(select(Installation).where(Installation.installation_id == inst_id))
        db_inst = res.scalars().first()
        if not db_inst:
            db_inst = Installation(
                installation_id=inst_id,
                account_id=account_id,
                account_login=account_login,
                account_type=account_type,
                user_id=user.id,
                repository_selection=repository_selection,
                permissions=permissions,
                events=events,
            )
            db.add(db_inst)
            await db.commit()
            await db.refresh(db_inst)
            print(f"Stored installation {inst_id} for user {user.email} (sender={sender_login})")
        else:
            db_inst.user_id = user.id
            db_inst.account_id = account_id
            db_inst.account_login = account_login
            db_inst.account_type = account_type
            db_inst.repository_selection = repository_selection
            db_inst.permissions = permissions
            db_inst.events = events
            # Re-install (same installation id reappears) — resume monitoring.
            db_inst.suspended_at = None
            db_inst.permissions_ok = True
            db.add(db_inst)
            await db.commit()
            await db.refresh(db_inst)
            print(f"Updated existing installation {inst_id} for user {user.email}")

        for r in payload.get("repositories", []):
            repo_gid = r.get("id")
            res = await db.execute(select(Repository).where(Repository.github_id == repo_gid))
            db_repo = res.scalars().first()
            if not db_repo:
                db_repo = Repository(
                    github_id=repo_gid,
                    name=r.get("name"),
                    full_name=r.get("full_name"),
                    is_private=r.get("private", False),
                    installation_id=db_inst.id,
                    reviews_enabled=True,
                )
                db.add(db_repo)
                print(f"Created repository {r.get('full_name')} from installation payload.")
            else:
                db_repo.installation_id = db_inst.id
                db_repo.name = r.get("name")
                db_repo.full_name = r.get("full_name")
                db_repo.is_private = r.get("private", False)
                db_repo.reviews_enabled = True
                # Explicit re-add: clear the Removed marker, history stays attached.
                if db_repo.removed_at is not None:
                    db_repo.removed_at = None
                    print(f"Re-activated previously removed repository {r.get('full_name')}.")
                db.add(db_repo)
                print(f"Re-linked repository {r.get('full_name')} to installation {db_inst.id}.")
        await db.commit()


async def handle_installation_deleted(payload: Dict[str, Any], delivery_id: str):
    print(f"[{delivery_id}] Handling installation.deleted event...")
    installation_payload = payload.get("installation", {})
    inst_id = installation_payload.get("id")

    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Installation).where(Installation.installation_id == inst_id))
        db_inst = res.scalars().first()
        if db_inst:
            repos_res = await db.execute(select(Repository).where(Repository.installation_id == db_inst.id))
            repos = repos_res.scalars().all()
            for r in repos:
                # Keep installation_id for history attribution; the removed_at
                # marker hides the repo from the active list.
                r.reviews_enabled = False
                if r.removed_at is None:
                    r.removed_at = datetime.now(timezone.utc)
                db.add(r)
                print(f"Marked repository {r.full_name} as removed due to app uninstallation.")

            # Keep the installation row for history attribution; mark it
            # suspended so the sync engine stops trying to fetch it.
            db_inst.suspended_at = datetime.now(timezone.utc)
            db_inst.permissions_ok = False
            db.add(db_inst)
            await db.commit()
            print(
                f"Marked installation {inst_id} as suspended while preserving "
                f"repositories and historical reviews."
            )


async def handle_installation_repositories(payload: Dict[str, Any], delivery_id: str):
    print(f"[{delivery_id}] Handling installation_repositories event...")
    installation_payload = payload.get("installation", {})
    inst_id = installation_payload.get("id")

    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Installation).where(Installation.installation_id == inst_id))
        db_inst = res.scalars().first()
        if not db_inst:
            print(f"Installation {inst_id} not found in DB.")
            return

        for r in payload.get("repositories_added", []):
            repo_gid = r.get("id")
            res = await db.execute(select(Repository).where(Repository.github_id == repo_gid))
            db_repo = res.scalars().first()
            if not db_repo:
                db_repo = Repository(
                    github_id=repo_gid,
                    name=r.get("name"),
                    full_name=r.get("full_name"),
                    is_private=r.get("private", False),
                    installation_id=db_inst.id,
                    reviews_enabled=True,
                )
                db.add(db_repo)
                print(f"Added repository {r.get('full_name')} from repositories_added webhook event.")
            else:
                db_repo.installation_id = db_inst.id
                db_repo.name = r.get("name")
                db_repo.full_name = r.get("full_name")
                db_repo.is_private = r.get("private", False)
                db_repo.reviews_enabled = True
                if db_repo.removed_at is not None:
                    db_repo.removed_at = None
                    print(f"Re-activated previously removed repository {r.get('full_name')}.")
                db.add(db_repo)
                print(f"Updated repository {r.get('full_name')} installation mapping.")

        for r in payload.get("repositories_removed", []):
            repo_gid = r.get("id")
            res = await db.execute(select(Repository).where(Repository.github_id == repo_gid))
            db_repo = res.scalars().first()
            if db_repo:
                # Keep installation_id for history attribution; removed_at
                # hides the repo from the active list.
                db_repo.reviews_enabled = False
                if db_repo.removed_at is None:
                    db_repo.removed_at = datetime.now(timezone.utc)
                db.add(db_repo)
                print(f"Marked repository {r.get('full_name')} as removed via webhook.")

        await db.commit()


async def handle_installation_permissions(payload: Dict[str, Any], delivery_id: str):
    """Handle installation.new_permissions_accepted.

    Updates the stored permission set and re-evaluates the review gate. If
    required permissions are missing, repos under this installation are
    surfaced as "Permission Required" and no new reviews are queued until
    permissions are restored.
    """
    print(f"[{delivery_id}] Handling installation.new_permissions_accepted event...")
    installation_payload = payload.get("installation", {})
    inst_id = installation_payload.get("id")
    permissions = installation_payload.get("permissions", {})

    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Installation).where(Installation.installation_id == inst_id))
        db_inst = res.scalars().first()
        if not db_inst:
            print(f"Installation {inst_id} not found in DB.")
            return
        if permissions:
            db_inst.permissions = permissions
        db_inst.permissions_ok = _has_required_permissions(db_inst.permissions, db_inst.suspended_at)
        db.add(db_inst)
        await db.commit()
        print(
            f"Installation {inst_id} permissions updated; permissions_ok={db_inst.permissions_ok}"
        )


async def handle_installation_suspend(payload: Dict[str, Any], delivery_id: str, suspended: bool):
    """Handle installation.suspend / installation.unsuspend."""
    print(f"[{delivery_id}] Handling installation.{'suspend' if suspended else 'unsuspend'} event...")
    installation_payload = payload.get("installation", {})
    inst_id = installation_payload.get("id")

    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Installation).where(Installation.installation_id == inst_id))
        db_inst = res.scalars().first()
        if not db_inst:
            print(f"Installation {inst_id} not found in DB.")
            return
        if suspended:
            db_inst.suspended_at = datetime.now(timezone.utc)
        else:
            db_inst.suspended_at = None
        db_inst.permissions_ok = _has_required_permissions(db_inst.permissions, db_inst.suspended_at)
        db.add(db_inst)
        await db.commit()
        print(f"Installation {inst_id} suspended_at={db_inst.suspended_at}")


async def get_pr_diff(owner: str, repo: str, pr_number: int, token: str) -> str:
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3.diff",
    }
    async with httpx.AsyncClient() as client:
        res = await client.get(url, headers=headers)
        res.raise_for_status()
        return res.text


async def handle_pr_opened(payload: Dict[str, Any], delivery_id: str, action: str = "opened"):
    from app.queue.dispatcher import enqueue_review_job
    async with AsyncSessionLocal() as db:
        repository = payload.get("repository", {})
        pull_request = payload.get("pull_request", {})
        pr_number = pull_request.get("number", 0)
        repo_github_id = repository.get("id")
        repo_full_name = repository.get("full_name", "")

        # Skip events for removed (uninstalled) repositories — belt & braces;
        # GitHub stops delivering once the repo leaves the installation.
        if repo_github_id:
            res = await db.execute(
                select(Repository).where(Repository.github_id == repo_github_id)
            )
            db_repo = res.scalars().first()
            if db_repo is not None and db_repo.removed_at is not None:
                print(f"[{delivery_id}] Ignoring PR #{pr_number} event for removed repository {db_repo.full_name}")
                return

        await enqueue_review_job(db, payload, delivery_id, webhook_action=action)

        # Keep the DB PR state in sync and drop the stale GitHub cache entry
        # so badges reflect the new state immediately.
        if repo_github_id:
            res = await db.execute(
                select(Repository).where(Repository.github_id == repo_github_id)
            )
            db_repo = res.scalars().first()
            if db_repo:
                pr_res = await db.execute(
                    select(PullRequest).where(
                        PullRequest.repo_id == db_repo.id,
                        PullRequest.pr_number == pr_number,
                    )
                )
                db_pr = pr_res.scalars().first()
                if db_pr:
                    if action == "reopened" and db_pr.status != "open":
                        db_pr.status = "open"
                        db.add(db_pr)
                        await db.commit()
                        print(f"[{delivery_id}] Marked PR #{pr_number} as open (reopened)")
                    elif action == "synchronize":
                        db_pr.head_sha = pull_request.get("head", {}).get("sha", db_pr.head_sha)
                        db.add(db_pr)
                        await db.commit()
        await github_service.invalidate_pr_cache(
            repo_full_name, pr_number
        )


async def handle_pr_closed(payload: Dict[str, Any], delivery_id: str):
    """Update DB PR state on close/merge and invalidate the GitHub cache."""
    repository = payload.get("repository", {})
    pull_request = payload.get("pull_request", {})
    pr_number = pull_request.get("number", 0)
    merged = bool(pull_request.get("merged", False))
    new_status = "merged" if merged else "closed"

    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(Repository).where(Repository.github_id == repository.get("id"))
        )
        db_repo = res.scalars().first()
        if db_repo and db_repo.removed_at is not None:
            print(f"[{delivery_id}] Ignoring PR #{pr_number} close event for removed repository {db_repo.full_name}")
            return
        if db_repo:
            pr_res = await db.execute(
                select(PullRequest).where(
                    PullRequest.repo_id == db_repo.id,
                    PullRequest.pr_number == pr_number,
                )
            )
            db_pr = pr_res.scalars().first()
            if db_pr and db_pr.status != new_status:
                db_pr.status = new_status
                db.add(db_pr)
                await db.commit()
                print(f"[{delivery_id}] Marked PR #{pr_number} as {new_status}")

        await github_service.invalidate_pr_cache(
            repository.get("full_name", ""), pr_number
        )


class GitHubWebhookService:
    @staticmethod
    def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
        if not signature or not secret:
            return False
        expected = "sha256=" + hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    @staticmethod
    async def process_webhook(event: str, action: str, payload: Dict[str, Any], delivery_id: str):
        print(f"Received webhook: event={event}, action={action}, delivery_id={delivery_id}")

        import json
        print(f"Webhook payload detail:\n{json.dumps(payload, indent=2)}")

        handlers = {
            ("pull_request", "opened"): lambda p, d: handle_pr_opened(p, d, "opened"),
            ("pull_request", "reopened"): lambda p, d: handle_pr_opened(p, d, "reopened"),
            ("pull_request", "synchronize"): lambda p, d: handle_pr_opened(p, d, "synchronize"),
            ("pull_request", "closed"): handle_pr_closed,
            ("installation", "created"): handle_installation_created,
            ("installation", "deleted"): handle_installation_deleted,
            ("installation", "new_permissions_accepted"): handle_installation_permissions,
            ("installation", "suspend"): lambda p, d: handle_installation_suspend(p, d, True),
            ("installation", "unsuspend"): lambda p, d: handle_installation_suspend(p, d, False),
            ("installation_repositories", "added"): handle_installation_repositories,
            ("installation_repositories", "removed"): handle_installation_repositories,
        }
        handler = handlers.get((event, action))
        if handler:
            await handler(payload, delivery_id)


github_webhook_service = GitHubWebhookService()

