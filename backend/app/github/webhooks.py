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
from app.ai.graph import build_review_graph
from app.ai.state import ReviewState


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

    async with AsyncSessionLocal() as db:
        res = await db.execute(select(User).order_by(User.created_at))
        user = res.scalars().first()
        if not user:
            print("No user found to link installation to.")
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
                events=events
            )
            db.add(db_inst)
            await db.commit()
            await db.refresh(db_inst)
            print(f"Stored installation {inst_id} for user {user.email}")

        # Add repositories in payload
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
                    reviews_enabled=True
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
            # Delete linked repositories
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
    action = payload.get("action")

    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Installation).where(Installation.installation_id == inst_id))
        db_inst = res.scalars().first()
        if not db_inst:
            print(f"Installation {inst_id} not found in DB.")
            return

        # 1. Handle added repositories
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
                    reviews_enabled=True
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

        # 2. Handle removed repositories
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
        "Accept": "application/vnd.github.v3.diff"
    }
    async with httpx.AsyncClient() as client:
        res = await client.get(url, headers=headers)
        res.raise_for_status()
        return res.text


async def run_pr_review_pipeline(payload: Dict[str, Any], delivery_id: str):
    review_id = None
    check_run_id = None
    owner = None
    repo_name = None

    try:
        installation_id = payload["installation"]["id"]
        repository = payload["repository"]
        pull_request = payload["pull_request"]
        owner = repository["owner"]["login"]
        repo_name = repository["name"]
        pr_number = pull_request["number"]
        pr_title = pull_request["title"]
        pr_body = pull_request.get("body", "") or ""
        head_sha = pull_request["head"]["sha"]
        head_branch = pull_request["head"]["ref"]
        base_branch = pull_request["base"]["ref"]
        author = pull_request["user"]["login"]
        additions = pull_request.get("additions", 0)
        deletions = pull_request.get("deletions", 0)
        changed_files = pull_request.get("changed_files", 0)

        # Get installation token
        token = await github_app_auth.get_installation_token(installation_id)

        # Get diff content
        diff_content = await get_pr_diff(owner, repo_name, pr_number, token)

        async with AsyncSessionLocal() as db:
            # Get installation + user
            res = await db.execute(select(Installation).where(Installation.installation_id == installation_id))
            db_inst = res.scalars().first()
            if not db_inst:
                print(f"Installation {installation_id} not found.")
                return
            user_id = db_inst.user_id

            # Get or create Repository record
            repo_github_id = repository.get("id")
            res = await db.execute(select(Repository).where(Repository.github_id == repo_github_id))
            db_repo = res.scalars().first()
            if not db_repo:
                db_repo = Repository(
                    github_id=repo_github_id,
                    name=repo_name,
                    full_name=repository.get("full_name"),
                    is_private=repository.get("private", False),
                    installation_id=db_inst.id,
                    reviews_enabled=True
                )
                db.add(db_repo)
                await db.commit()
                await db.refresh(db_repo)

            # Get or create PullRequest record
            res = await db.execute(
                select(PullRequest).where(
                    PullRequest.repo_id == db_repo.id,
                    PullRequest.pr_number == pr_number
                )
            )
            db_pr = res.scalars().first()
            if not db_pr:
                db_pr = PullRequest(
                    repo_id=db_repo.id,
                    pr_number=pr_number,
                    title=pr_title,
                    author=author,
                    head_sha=head_sha,
                    head_branch=head_branch,
                    base_branch=base_branch,
                    status="open",
                    additions=additions,
                    deletions=deletions,
                    changed_files=changed_files,
                )
                db.add(db_pr)
                await db.commit()
                await db.refresh(db_pr)

            # Create Review record with status "pending"
            db_review = Review(
                pr_id=db_pr.id,
                status="running",
                started_at=datetime.now(timezone.utc),
            )
            db.add(db_review)
            await db.commit()
            await db.refresh(db_review)
            review_id = db_review.id
            print(f"Created Review record {review_id} for PR #{pr_number}")

        # Create GitHub check run
        print(f"Creating check run for PR #{pr_number}...")
        check_run = await github_client.create_check_run(
            installation_id=installation_id,
            owner=owner,
            repo=repo_name,
            name="Revora AI Review",
            head_sha=head_sha,
            status="in_progress"
        )
        check_run_id = check_run.get("id")

        # Determine AI provider
        from app.core.config import settings
        if settings.GEMINI_API_KEY:
            provider = "gemini"
            model = "gemini-3.1-flash-lite"
        elif settings.OPENAI_API_KEY:
            provider = "openai"
            model = "gpt-4o"
        else:
            provider = "gemini"
            model = "gemini-3.1-flash-lite"

        # Run AI graph
        initial_state = ReviewState(
            pr_number=pr_number,
            pr_title=pr_title,
            pr_description=pr_body,
            diff_content=diff_content,
            repo_context="No additional context.",
            user_id=str(user_id),
            provider=provider,
            model=model,
            bug_analysis=[],
            security_analysis=[],
            performance_analysis=[],
            style_analysis=[],
            final_review_markdown=""
        )

        print(f"Running AI review agents for PR #{pr_number}...")
        graph = build_review_graph()
        final_state = await graph.ainvoke(initial_state)
        review_markdown = final_state.get("final_review_markdown", "No review comments generated.")

        # Persist review result to DB
        async with AsyncSessionLocal() as db:
            res = await db.execute(select(Review).where(Review.id == review_id))
            db_review = res.scalars().first()
            if db_review:
                db_review.status = "completed"
                db_review.summary = review_markdown
                db_review.completed_at = datetime.now(timezone.utc)
                db_review.stats = {
                    "provider": provider,
                    "model": model,
                }
                await db.commit()
                print(f"Review {review_id} saved to database.")

        # Post PR review comment on GitHub
        print(f"Posting review comment to GitHub PR #{pr_number}...")
        await github_client.create_pr_review(
            installation_id=installation_id,
            owner=owner,
            repo=repo_name,
            pull_number=pr_number,
            body=review_markdown,
            event="COMMENT"
        )

        # Update check run to completed
        if check_run_id:
            await github_client.update_check_run(
                installation_id=installation_id,
                owner=owner,
                repo=repo_name,
                check_run_id=check_run_id,
                status="completed",
                output={
                    "title": "Review Complete",
                    "summary": "Revora has successfully analyzed your pull request.",
                    "conclusion": "success"
                }
            )

    except Exception as e:
        print(f"Error in run_pr_review_pipeline: {e}")
        # Mark review as failed in DB
        if review_id:
            try:
                async with AsyncSessionLocal() as db:
                    res = await db.execute(select(Review).where(Review.id == review_id))
                    db_review = res.scalars().first()
                    if db_review:
                        db_review.status = "failed"
                        db_review.error_message = str(e)
                        db_review.completed_at = datetime.now(timezone.utc)
                        await db.commit()
            except Exception:
                pass

        # Mark check run as failed on GitHub
        if check_run_id and owner and repo_name:
            try:
                await github_client.update_check_run(
                    installation_id=payload.get("installation", {}).get("id"),
                    owner=owner,
                    repo=repo_name,
                    check_run_id=check_run_id,
                    status="completed",
                    output={
                        "title": "Review Failed",
                        "summary": f"An error occurred during review: {e}",
                        "conclusion": "failure"
                    }
                )
            except Exception:
                pass


async def handle_pr_opened(payload: Dict[str, Any], delivery_id: str):
    asyncio.create_task(run_pr_review_pipeline(payload, delivery_id))


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
        
        # Comprehensive log of incoming webhook request payloads for debugging sync issue
        import json
        print(f"Webhook payload detail:\n{json.dumps(payload, indent=2)}")

        handlers = {
            ("pull_request", "opened"): handle_pr_opened,
            ("pull_request", "reopened"): handle_pr_opened,
            ("installation", "created"): handle_installation_created,
            ("installation", "deleted"): handle_installation_deleted,
            ("installation_repositories", "added"): handle_installation_repositories,
            ("installation_repositories", "removed"): handle_installation_repositories,
        }
        handler = handlers.get((event, action))
        if handler:
            await handler(payload, delivery_id)


github_webhook_service = GitHubWebhookService()
