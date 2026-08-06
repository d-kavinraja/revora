"""Shared utilities for webhook and pipeline operations.

Extracted from duplicated logic in webhooks.py and orchestrator.py.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.github import Installation, PullRequest, Repository
from app.models.review import Review
from app.models.user import User
from app.orchestrator.models import (
    CONFIG_SOURCE_NONE,
    CONFIG_SOURCE_REPO,
    CONFIG_SOURCE_ROUTING,
)
from app.services.api_key_service import api_key_service
from app.services.provider_registry import provider_registry_service

logger = logging.getLogger(__name__)

_TERMINAL_REVIEW_STATUSES = {"completed", "failed", "cancelled", "stopped", "timed_out"}


async def resolve_provider_config(
    db_session,
    user_id: str,
    db_repo: Repository | None = None,
) -> tuple[str | None, str | None, str | None, str]:
    """Resolve LLM provider, model, and API key ID.

    Priority: repo settings > user routing preferences.

    Returns:
        Tuple of (provider, model, api_key_id, config_source)
        config_source is one of:
            "repo_config"  — MODE 1: repo has explicit mapping (fail-fast)
            "user_routing" — MODE 2: user routing preferences applied
            "none"         — MODE 3: nothing configured (caller must stop)
    """
    provider = None
    model = None
    api_key_id = None
    config_source = CONFIG_SOURCE_NONE

    # 1. Repo-level config (MODE 1)
    if db_repo and db_repo.settings:
        provider = db_repo.settings.get("assigned_provider")
        model = db_repo.settings.get("assigned_model")
        api_key_id = db_repo.settings.get("assigned_key_id")
        if provider and model:
            # Verify the referenced API key still exists before committing to MODE 1
            key_valid = False
            if api_key_id:
                try:
                    db_key = await api_key_service.get_by_id(
                        db_session, uuid.UUID(api_key_id)
                    )
                    if db_key and str(db_key.user_id) == user_id and db_key.is_valid:
                        key_valid = True
                except Exception:
                    pass
            if not api_key_id or key_valid:
                config_source = CONFIG_SOURCE_REPO
                logger.info(f"MODE 1 (repo config): {provider}/{model}")
                return provider, model, api_key_id, config_source
            # Key was deleted or invalid — auto-clean the stale mapping and fall through
            logger.warning(
                f"MODE 1 key id={api_key_id} not found or invalid for user={user_id}. "
                f"Clearing stale repo mapping and falling through to MODE 2."
            )
            try:
                merged_repo = await db_session.merge(db_repo)
                new_settings = dict(merged_repo.settings or {})
                new_settings.pop("assigned_provider", None)
                new_settings.pop("assigned_model", None)
                new_settings.pop("assigned_key_id", None)
                merged_repo.settings = new_settings
                await db_session.commit()
            except Exception as cleanup_e:
                logger.warning(f"Failed to auto-clean stale repo mapping: {cleanup_e}")

    # 2. User routing preferences (MODE 2)
    try:
        user_result = await db_session.execute(select(User).where(User.id == user_id))
        db_user = user_result.scalars().first()
        if db_user and db_user.settings:
            routing_prefs = db_user.settings.get("model_routing", {})
            code_review_pref = routing_prefs.get("code_review", {})
            pref_provider = code_review_pref.get("provider")
            pref_model = code_review_pref.get("model")
            if pref_provider and pref_model:
                provider = pref_provider
                model = pref_model
                user_keys = await api_key_service.get_all_usable_keys(
                    db_session, user_id
                )
                if provider in user_keys:
                    api_key_id = str(user_keys[provider].id)
                    config_source = CONFIG_SOURCE_ROUTING
                    logger.info(f"MODE 2 (user routing): {provider}/{model}")
                    return provider, model, api_key_id, config_source
                # Routing prefs exist but no usable key for this provider — fall through
                logger.warning(
                    f"MODE 2 routing prefers {provider} but no usable key found. "
                    f"Falling through."
                )
    except Exception as e:
        logger.warning(f"Error reading routing preferences: {e}")

    return None, None, None, CONFIG_SOURCE_NONE


async def build_available_providers_for_user(
    db_session,
    user_id: str,
) -> list[tuple[str, str, str]]:
    """Discover available providers from user's configured API keys.

    Used for MODE 2 routing when the repo has no explicit config.
    Returns sorted list of (provider, default_model, api_key_id).
    """
    user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    user_keys = await api_key_service.get_all_usable_keys(db_session, user_uuid)
    providers = await provider_registry_service.get_enabled(db_session)

    available = []
    for provider in providers:
        if provider.name in user_keys:
            key = user_keys[provider.name]
            available.append((provider.name, provider.default_model, str(key.id)))

    # Already ordered by provider_registry.priority (from get_enabled)
    return available


async def get_or_create_review_records(
    installation_id: int,
    repository: dict,
    pull_request: dict,
    delivery_id: str,
    status: str = "running",
    find_existing_pending: bool = True,
    existing_review_id: str | None = None,
) -> tuple[Review, Repository, PullRequest, str]:
    """Get or create Installation, Repository, PullRequest, and Review records.

    Args:
        existing_review_id: If provided (lifecycle jobs), use this exact review
            record instead of searching for a pending one or creating a new one.

    Returns:
        Tuple of (db_review, db_repo, db_pr, user_id)
    """
    repo_github_id = repository.get("id")
    pr_number = pull_request["number"]
    head_sha = pull_request["head"]["sha"]

    async with AsyncSessionLocal() as db:
        # Get installation
        res = await db.execute(
            select(Installation).where(Installation.installation_id == installation_id)
        )
        db_inst = res.scalars().first()
        if not db_inst:
            raise ValueError(f"Installation {installation_id} not found.")
        user_id = str(db_inst.user_id)

        # Get or create Repository
        res = await db.execute(
            select(Repository).where(Repository.github_id == repo_github_id)
        )
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
        elif db_repo.installation_id != db_inst.id:
            db_repo.installation_id = db_inst.id
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
                db_pr.changed_files = pull_request.get(
                    "changed_files", db_pr.changed_files
                )
                await db.commit()

        db_review = None
        review_transitioned = False
        if existing_review_id:
            # Lifecycle job: use the exact review created by the lifecycle action
            try:
                rid = uuid.UUID(existing_review_id)
            except ValueError:
                rid = None
            if rid:
                res = await db.execute(select(Review).where(Review.id == rid))
                db_review = res.scalars().first()
                if (
                    db_review
                    and db_review.status != status
                    and db_review.status not in _TERMINAL_REVIEW_STATUSES
                ):
                    db_review.status = status
                    if status == "running":
                        db_review.started_at = datetime.now(UTC)
                    review_transitioned = True
                    await db.commit()
                    await db.refresh(db_review)
                    logger.info(
                        f"Updated lifecycle Review {db_review.id} to {status} for PR #{pr_number}"
                    )
                elif db_review and db_review.status in _TERMINAL_REVIEW_STATUSES:
                    logger.warning(
                        f"Lifecycle Review {db_review.id} is already {db_review.status} "
                        f"— not resurrecting to {status} for PR #{pr_number}"
                    )
        if not db_review and find_existing_pending:
            res = await db.execute(
                select(Review)
                .where(Review.pr_id == db_pr.id, Review.status == "pending")
                .order_by(Review.created_at.desc())
            )
            db_review = res.scalars().first()
            if db_review:
                if db_review.status != status:
                    db_review.status = status
                    if status == "running":
                        db_review.started_at = datetime.now(UTC)
                    review_transitioned = True
                    await db.commit()
                    await db.refresh(db_review)
                    logger.info(
                        f"Updated pending Review {db_review.id} to {status} for PR #{pr_number}"
                    )

        if not db_review and find_existing_pending:
            # No pending review for this PR. The dispatcher always pre-creates
            # the Review row at enqueue time, so "no pending row" at execution
            # time means the job's lifecycle review was cancelled/failed/etc.
            # while the job waited — NEVER resurrect it with a new row. Return
            # the latest review so callers can detect the terminal state.
            latest = await db.execute(
                select(Review)
                .where(Review.pr_id == db_pr.id)
                .order_by(Review.created_at.desc())
                .limit(1)
            )
            db_review = latest.scalars().first()
            if db_review:
                logger.warning(
                    f"Existing Review {db_review.id} ({db_review.status}) found for PR #{pr_number} "
                    f"— not creating a new row for stale job {delivery_id[:12]}"
                )

        if not db_review:
            # Create Review record (brand-new PR lifecycle only)
            db_review = Review(
                pr_id=db_pr.id,
                status=status,
                started_at=datetime.now(UTC) if status == "running" else None,
            )
            db.add(db_review)
            review_transitioned = True
            await db.commit()
            await db.refresh(db_review)
            logger.info(
                f"Created Review record {db_review.id} for PR #{pr_number} with status {status}"
            )

        # Track this run as a ReviewExecution (queued → running).
        try:
            from app.models.execution import ReviewExecution as ExecModel
            from app.services.review_execution_service import (
                create_execution,
                mark_execution_running,
            )

            existing_exec_id = await db.scalar(
                select(ExecModel.id).where(ExecModel.review_id == db_review.id).limit(1)
            )
            if not existing_exec_id:
                await create_execution(
                    db, db_review.id, trigger="webhook", commit_sha=head_sha
                )
            if status == "running" and review_transitioned:
                await mark_execution_running(db, db_review.id)
            await db.commit()
        except Exception as e:
            logger.warning(f"Failed to sync review execution for {db_review.id}: {e}")

        # Resolve provider config and create immutable execution context (skip if already exists)
        try:
            from app.models.exec_context import ReviewExecutionContext

            existing_ctx = await db.execute(
                select(ReviewExecutionContext).where(
                    ReviewExecutionContext.review_id == db_review.id
                )
            )
            if existing_ctx.scalars().first():
                logger.info(
                    f"Execution context already exists for review {db_review.id} — skipping creation"
                )
            else:
                provider, model, api_key_id, _source = await resolve_provider_config(
                    db, user_id=str(db_inst.user_id), db_repo=db_repo
                )
                if provider and model:
                    exec_ctx = ReviewExecutionContext(
                        review_id=db_review.id,
                        repository_full_name=db_repo.full_name,
                        provider=provider,
                        api_key_id=uuid.UUID(api_key_id) if api_key_id else None,
                        model=model,
                        commit_sha=head_sha,
                        base_branch=pull_request["base"]["ref"],
                        head_branch=pull_request["head"]["ref"],
                        pr_number=pr_number,
                        configuration_snapshot=db_repo.settings or {},
                    )
                    db.add(exec_ctx)
                    await db.commit()
                    logger.info(
                        f"Created execution context for review {db_review.id}: {provider}/{model}"
                    )
        except Exception as e:
            logger.warning(
                f"Failed to create execution context for review {db_review.id}: {e}"
            )

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
    api_key_id: str | None = None,
):
    """Record token usage for analytics and usage dashboards."""
    if not settings.USAGE_ANALYTICS_ENABLED:
        logger.debug(
            "[usage] USAGE_ANALYTICS_ENABLED=False, skipping record_usage_stats"
        )
        return
    try:
        from app.services.cost_estimator import cost_estimator
        from app.services.token_manager import token_manager
        from app.services.usage_tracker import usage_tracker

        input_cost = round(cost_estimator.estimate(provider, input_tokens, 0), 8)
        output_cost = round(cost_estimator.estimate(provider, 0, output_tokens), 8)

        parsed_user_id = None
        if user_id:
            try:
                parsed_user_id = (
                    uuid.UUID(user_id) if isinstance(user_id, str) else user_id
                )
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
                    started_at=datetime.now(UTC),
                    was_fallback=is_fallback,
                    review_id=review_id,
                )
    except Exception as ue:
        logger.error(f"Failed to record usage stats: {ue}", exc_info=True)
