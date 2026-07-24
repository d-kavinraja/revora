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
from app.pipeline.orchestrator import review_pipeline


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
                await db.delete(r)
                print(f"Deleted repository {r.full_name} due to app uninstallation.")

            await db.delete(db_inst)
            await db.commit()
            print(f"Successfully deleted installation {inst_id} and its repositories.")


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
                db.add(db_repo)
                print(f"Updated repository {r.get('full_name')} installation mapping.")

        for r in payload.get("repositories_removed", []):
            repo_gid = r.get("id")
            res = await db.execute(select(Repository).where(Repository.github_id == repo_gid))
            db_repo = res.scalars().first()
            if db_repo:
                await db.delete(db_repo)
                print(f"Removed repository {r.get('full_name')} from database via webhook.")

        await db.commit()


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


async def handle_pr_opened(payload: Dict[str, Any], delivery_id: str):
    from app.queue.dispatcher import enqueue_review_job
    async with AsyncSessionLocal() as db:
        await enqueue_review_job(db, payload, delivery_id)


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
            ("pull_request", "opened"): handle_pr_opened,
            ("pull_request", "reopened"): handle_pr_opened,
            ("pull_request", "synchronize"): handle_pr_opened,
            ("installation", "created"): handle_installation_created,
            ("installation", "deleted"): handle_installation_deleted,
            ("installation_repositories", "added"): handle_installation_repositories,
            ("installation_repositories", "removed"): handle_installation_repositories,
        }
        handler = handlers.get((event, action))
        if handler:
            await handler(payload, delivery_id)


github_webhook_service = GitHubWebhookService()

