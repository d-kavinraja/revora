"""Shared utilities for webhook and pipeline operations.

Extracted from duplicated logic in webhooks.py and orchestrator.py.
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.github import Installation, Repository, PullRequest
from app.models.review import Review
from app.models.user import User
from app.services.api_key_service import api_key_service

logger = logging.getLogger(__name__)


COST_TABLE = {
    "gemini":    {"input": 0.000075, "output": 0.0003},
    "openai":    {"input": 0.0025,   "output": 0.01},
    "anthropic": {"input": 0.003,    "output": 0.015},
    "deepseek":  {"input": 0.00014,  "output": 0.00028},
    "groq":      {"input": 0.00059,  "output": 0.00079},
}


async def resolve_provider_config(
    db_session,
    user_id: str,
    db_repo: Optional[Repository] = None,
) -> tuple[str, str, Optional[str]]:
    """Resolve LLM provider, model, and API key ID.

    Priority: repo settings > user routing preferences > env defaults.

    Returns:
        Tuple of (provider, model, api_key_id)
    """
    provider = None
    model = None
    api_key_id = None

    # 1. Repo-level config
    if db_repo and db_repo.settings:
        provider = db_repo.settings.get("assigned_provider")
        model = db_repo.settings.get("assigned_model")
        api_key_id = db_repo.settings.get("assigned_key_id")

    # 2. User routing preferences
    if not provider or not model:
        try:
            user_result = await db_session.execute(
                select(User).where(User.id == user_id)
            )
            db_user = user_result.scalars().first()
            if db_user and db_user.settings:
                routing_prefs = db_user.settings.get("model_routing", {})
                code_review_pref = routing_prefs.get("code_review", {})
                pref_provider = code_review_pref.get("provider")
                pref_model = code_review_pref.get("model")
                if pref_provider and pref_model:
                    provider = pref_provider
                    model = pref_model
                    user_keys = await api_key_service.get_all_usable_keys(db_session, user_id)
                    if provider in user_keys:
                        api_key_id = str(user_keys[provider].id)
                    logger.info(f"Using default routing preference: {provider}/{model}")
        except Exception as e:
            logger.warning(f"Error reading routing preferences: {e}")

    # 3. Env defaults
    if not provider or not model:
        from app.core.config import settings
        if settings.GEMINI_API_KEY:
            provider = "gemini"
            model = "gemini-2.5-flash"
        elif settings.OPENAI_API_KEY:
            provider = "openai"
            model = "gpt-4o"
        else:
            provider = "gemini"
            model = "gemini-2.5-flash"

    return provider, model, api_key_id


async def get_or_create_review_records(
    installation_id: int,
    repository: dict,
    pull_request: dict,
    delivery_id: str,
    status: str = "running",
    find_existing_pending: bool = True,
) -> tuple[Review, Repository, PullRequest, str]:
    """Get or create Installation, Repository, PullRequest, and Review records.

    Returns:
        Tuple of (db_review, db_repo, db_pr, user_id)
    """
    repo_github_id = repository.get("id")
    pr_number = pull_request["number"]
    head_sha = pull_request["head"]["sha"]

    async with AsyncSessionLocal() as db:
        # Get installation
        res = await db.execute(select(Installation).where(Installation.installation_id == installation_id))
        db_inst = res.scalars().first()
        if not db_inst:
            raise ValueError(f"Installation {installation_id} not found.")
        user_id = str(db_inst.user_id)

        # Get or create Repository
        res = await db.execute(select(Repository).where(Repository.github_id == repo_github_id))
        db_repo = res.scalars().first()
        if not db_repo:
            db_repo = Repository(
                github_id=repo_github_id,
                name=repository["name"],
                full_name=repository.get("full_name"),
                is_private=repository.get("private", False),
                installation_id=db_inst.id,
                reviews_enabled=True,
            )
            db.add(db_repo)
            await db.commit()
            await db.refresh(db_repo)

        # Get or create PullRequest
        res = await db.execute(
            select(PullRequest).where(
                PullRequest.repo_id == db_repo.id,
                PullRequest.pr_number == pr_number,
            )
        )
        db_pr = res.scalars().first()
        if not db_pr:
            db_pr = PullRequest(
                repo_id=db_repo.id,
                pr_number=pr_number,
                title=pull_request["title"],
                author=pull_request["user"]["login"],
                head_sha=head_sha,
                head_branch=pull_request["head"]["ref"],
                base_branch=pull_request["base"]["ref"],
                status="open",
                additions=pull_request.get("additions", 0),
                deletions=pull_request.get("deletions", 0),
                changed_files=pull_request.get("changed_files", 0),
            )
            db.add(db_pr)
            await db.commit()
            await db.refresh(db_pr)
        else:
            # Update the head sha in case this is a new push
            if db_pr.head_sha != head_sha:
                db_pr.head_sha = head_sha
                db_pr.additions = pull_request.get("additions", db_pr.additions)
                db_pr.deletions = pull_request.get("deletions", db_pr.deletions)
                db_pr.changed_files = pull_request.get("changed_files", db_pr.changed_files)
                await db.commit()

        db_review = None
        if find_existing_pending:
            res = await db.execute(
                select(Review).where(
                    Review.pr_id == db_pr.id,
                    Review.status == "pending"
                ).order_by(Review.created_at.desc())
            )
            db_review = res.scalars().first()
            if db_review:
                if db_review.status != status:
                    db_review.status = status
                    if status == "running":
                        db_review.started_at = datetime.now(timezone.utc)
                    await db.commit()
                    await db.refresh(db_review)
                    logger.info(f"Updated pending Review {db_review.id} to {status} for PR #{pr_number}")

        if not db_review:
            # Create Review record
            db_review = Review(
                pr_id=db_pr.id,
                status=status,
                started_at=datetime.now(timezone.utc) if status == "running" else None,
            )
            db.add(db_review)
            await db.commit()
            await db.refresh(db_review)
            logger.info(f"Created Review record {db_review.id} for PR #{pr_number} with status {status}")

        return db_review, db_repo, db_pr, user_id


async def record_usage_stats(
    review_id,
    user_id: str,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: float,
    is_fallback: bool = False,
    api_key_id: Optional[str] = None,
):
    """Record token usage for analytics and usage dashboards."""
    try:
        from app.services.token_manager import token_manager
        from app.services.usage_tracker import usage_tracker

        rates = COST_TABLE.get(provider, {"input": 0.001, "output": 0.003})
        input_cost = round((input_tokens * rates["input"]) / 1000, 8)
        output_cost = round((output_tokens * rates["output"]) / 1000, 8)

        parsed_user_id = None
        if user_id:
            try:
                parsed_user_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
            except Exception:
                pass

        if parsed_user_id:
            async with AsyncSessionLocal() as usage_db:
                await token_manager.record_usage(
                    db=usage_db,
                    user_id=parsed_user_id,
                    provider=provider,
                    model=model,
                    api_key_id=api_key_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    input_cost_usd=input_cost,
                    output_cost_usd=output_cost,
                    feature="code_review",
                    latency_ms=latency_ms,
                    is_fallback=is_fallback,
                    review_id=review_id,
                )

            async with AsyncSessionLocal() as log_db:
                await usage_tracker.log_request(
                    db=log_db,
                    request_id=str(uuid.uuid4()),
                    user_id=parsed_user_id,
                    provider=provider,
                    model=model,
                    api_key_id=api_key_id,
                    feature="code_review",
                    messages=[],
                    status="success",
                    latency_ms=latency_ms,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=input_cost + output_cost,
                    started_at=datetime.now(timezone.utc),
                    was_fallback=is_fallback,
                    review_id=review_id,
                )
    except Exception as ue:
        logger.error(f"Failed to record usage stats: {ue}", exc_info=True)

