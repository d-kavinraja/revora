"""Review pipeline orchestrator.

Orchestrates the full Context Engineering review pipeline with
per-stage error handling and graceful degradation.
"""

import time
import uuid
import logging
import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.review import Review
from app.models.github import PullRequest, Repository
from app.sse.emitter import SSEEmitter
from app.sse.events import EventType
from app.intelligence.engine import intelligence_engine
from app.indexing.indexer import repository_indexer
from app.knowledge.knowledge_store import knowledge_store
from app.retrieval.engine import retrieval_engine
from app.retrieval.models import RetrievalConfig
from app.retrieval.init import initialize_retrieval_engine
from app.retrieval.token_budget_engine import token_budget_engine
from app.prompt_engine.builder import prompt_builder
from app.prompt_engine.models import ReviewType
from app.orchestrator.orchestrator import llm_orchestrator
from app.verification.engine import verification_engine
from app.github_review.generator import github_review_generator
from app.security.content_guard import sanitize_input
from app.github.client import github_client
from app.ai.git_utils import GitService

logger = logging.getLogger(__name__)

# Initialize the retrieval engine with all retrievers, scorers, and strategies
initialize_retrieval_engine()


class ReviewPipeline:
    """Orchestrates the full Context Engineering review pipeline.

    Each stage has independent error handling. A failure in one stage
    causes graceful degradation rather than pipeline failure.
    """

    async def execute(
        self,
        review_id: uuid.UUID,
        installation_id: int,
        owner: str,
        repo_name: str,
        pr_number: int,
        pr_title: str,
        pr_description: str,
        head_sha: str,
        diff_content: str,
        user_id: str,
        provider: str = "gemini",
        model: str = None,
        clone_url: str = None,
        token: str = None,
        api_key_id: str = None,
    ) -> dict:
        """Execute the full review pipeline.

        Args:
            review_id: Review UUID.
            installation_id: GitHub installation ID.
            owner: Repository owner.
            repo_name: Repository name.
            pr_number: Pull request number.
            pr_title: PR title.
            pr_description: PR description.
            head_sha: HEAD commit SHA.
            diff_content: PR diff content.
            user_id: User UUID.
            provider: LLM provider name.
            model: Optional model override.
            clone_url: Optional clone URL for the repository.
            token: Optional GitHub token for cloning.

        Returns:
            Dict with status and metrics.
        """
        start = time.time()
        emitter = SSEEmitter(str(review_id))
        metrics = {}
        repo_path = None
        check_run_id = None

        try:
            # Stage 1: Prepare
            await emitter.emit("preparing_review", "running", EventType.STAGE_START)
            await emitter.emit_log("preparing_review", f"Starting review for PR #{pr_number}")
            
            try:
                from app.github.client import GitHubClient
                check_run = await GitHubClient().create_check_run(
                    installation_id=installation_id,
                    owner=owner,
                    repo=repo_name,
                    name="Revora AI Review",
                    head_sha=head_sha,
                    status="in_progress"
                )
                check_run_id = check_run.get("id")
            except Exception as e:
                logger.warning(f"Failed to create GitHub check run: {e}")

            # Stage 2: Clone repository
            repo_path = await self._stage_clone(emitter, clone_url, token, head_sha)

            # Stage 3: Intelligence analysis (if cloned)
            intelligence_data = await self._stage_intelligence(emitter, repo_path)

            # Stage 4: Indexing (if cloned)
            index = await self._stage_indexing(emitter, repo_path, owner, repo_name, head_sha)

            # Cleanup cloned repo immediately after indexing
            # (Removed early cleanup so Verification Engine can access the files)
            # Cleanup will be handled in the finally block.

            # Stage 5: Knowledge retrieval
            conventions, rules, repo_id = await self._stage_knowledge(
                emitter, owner, repo_name
            )

            # Stage 6: Context retrieval
            retrieval_result = await self._stage_retrieval(
                emitter, index, diff_content, repo_id=repo_id
            )

            # Stage 7: Build prompt
            prompt = await self._stage_prompt(
                emitter, intelligence_data, conventions, rules,
                diff_content, retrieval_result, provider
            )

            # Stage 8: LLM call
            llm_response = await self._stage_llm(
                emitter, prompt, user_id, provider, model, api_key_id
            )
            metrics.update({
                "provider": llm_response.provider,
                "model": llm_response.model,
                "input_tokens": llm_response.input_tokens,
                "output_tokens": llm_response.output_tokens,
                "estimated_cost": llm_response.estimated_cost_usd,
            })

            # Stage 9: Verification
            verified = await self._stage_verification(
                emitter, llm_response.content, repo_path or ".", diff_content, str(review_id)
            )

            # Stage 10: Generate and publish review
            review_summary_body = await self._stage_publish(
                emitter, verified, pr_title, installation_id,
                owner, repo_name, pr_number, intelligence_data,
                llm_response, start
            )

            # Save to DB
            await self._save_completed(
                review_id, verified, llm_response, metrics, start, user_id, review_summary_body, api_key_id
            )

            # Complete
            duration_ms = (time.time() - start) * 1000
            await emitter.emit("completed", "completed", EventType.REVIEW_COMPLETE, metrics={
                "duration_ms": duration_ms,
                **metrics,
            })

            if check_run_id:
                try:
                    from app.github.client import GitHubClient
                    await GitHubClient().update_check_run(
                        installation_id=installation_id,
                        owner=owner,
                        repo=repo_name,
                        check_run_id=check_run_id,
                        status="completed",
                        output={
                            "title": "Revora Review Complete",
                            "summary": f"Review completed in {duration_ms/1000:.1f}s. {verified.verified_count} findings verified.",
                            "conclusion": "success"
                        }
                    )
                except Exception as e:
                    logger.warning(f"Failed to update check run: {e}")

            return {"status": "success", "duration_ms": duration_ms, "metrics": metrics}

        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            await emitter.emit_error("pipeline", str(e))

            # Mark review as failed
            await self._save_failed(review_id, str(e))

            if check_run_id:
                try:
                    from app.github.client import GitHubClient
                    await GitHubClient().update_check_run(
                        installation_id=installation_id,
                        owner=owner,
                        repo=repo_name,
                        check_run_id=check_run_id,
                        status="completed",
                        output={
                            "title": "Revora Review Failed",
                            "summary": f"Pipeline error: {e}",
                            "conclusion": "failure"
                        }
                    )
                except Exception:
                    pass

            return {"status": "failed", "error": str(e)}

        finally:
            # Ensure repo cleanup
            if repo_path:
                try:
                    await GitService.cleanup_repository(repo_path)
                except Exception as e:
                    logger.warning(f"Failed to cleanup repo: {e}")

    async def _stage_clone(self, emitter, clone_url, token, head_sha=None):
        """Stage: Clone repository."""
        await emitter.emit("cloning_repository", "running", EventType.STAGE_START)

        if not clone_url or not token:
            await emitter.emit("cloning_repository", "skipped", EventType.STAGE_SKIPPED,
                             message="No clone URL provided")
            return None

        try:
            repo_path = await GitService.clone_repository(clone_url, token, head_sha)
            await emitter.emit("cloning_repository", "completed", EventType.STAGE_COMPLETE)
            return repo_path
        except Exception as e:
            logger.warning(f"Clone failed: {e}")
            await emitter.emit("cloning_repository", "failed", EventType.STAGE_FAILED,
                             message=str(e))
            return None

    async def _stage_intelligence(self, emitter, repo_path):
        """Stage: Repository intelligence analysis."""
        if not repo_path:
            await emitter.emit("analyzing_repository", "skipped", EventType.STAGE_SKIPPED)
            return {}

        await emitter.emit("analyzing_repository", "running", EventType.STAGE_START)

        try:
            intelligence = await intelligence_engine.analyze(repo_path)
            intelligence_data = intelligence.to_dict()
            await emitter.emit("detecting_languages", "completed",
                             metrics={"languages": len(intelligence.languages)})
            await emitter.emit("detecting_frameworks", "completed",
                             metrics={"frameworks": len(intelligence.frameworks)})
            await emitter.emit("analyzing_architecture", "completed",
                             metrics={"pattern": intelligence.architecture.pattern
                                     if intelligence.architecture else "unknown"})
            await emitter.emit("analyzing_repository", "completed",
                             EventType.STAGE_COMPLETE, metrics=intelligence_data)
            return intelligence_data
        except Exception as e:
            logger.warning(f"Intelligence analysis failed: {e}")
            await emitter.emit("analyzing_repository", "failed", EventType.STAGE_FAILED,
                             message=str(e))
            return {}

    async def _stage_indexing(self, emitter, repo_path, owner, repo_name, head_sha):
        """Stage: Code graph indexing with Redis L2 read-through cache."""
        if not repo_path:
            await emitter.emit("indexing_repository", "skipped", EventType.STAGE_SKIPPED)
            return None

        await emitter.emit("indexing_repository", "running", EventType.STAGE_START)

        # Retrieve repo_id
        repo_id_str = f"{owner}/{repo_name}"
        
        try:
            from app.cache.graph_cache import graph_cache
            
            # Check cache
            cached_index = await graph_cache.get_index(repo_id_str, head_sha)
            if cached_index:
                await emitter.emit("indexing_repository", "completed", EventType.STAGE_COMPLETE, metrics={"cache_hit": True})
                return cached_index

            index = await repository_indexer.build_index(repo_path)
            
            # Save to cache
            await graph_cache.set_index(repo_id_str, index, head_sha)

            await emitter.emit("building_dependency_graph", "completed")
            await emitter.emit("building_call_graph", "completed")
            await emitter.emit("building_import_graph", "completed")
            await emitter.emit("building_ast", "completed")
            await emitter.emit("indexing_repository", "completed", EventType.STAGE_COMPLETE, metrics={"cache_hit": False})
            return index
        except Exception as e:
            logger.warning(f"Indexing failed: {e}")
            await emitter.emit("indexing_repository", "failed", EventType.STAGE_FAILED,
                             message=str(e))
            return None

    async def _stage_knowledge(self, emitter, owner, repo_name):
        """Stage: Knowledge retrieval."""
        await emitter.emit("retrieving_repository_knowledge", "running", EventType.STAGE_START)

        conventions = ""
        rules = []

        try:
            async with AsyncSessionLocal() as db:
                repo_result = await db.execute(
                    select(Repository).where(Repository.full_name == f"{owner}/{repo_name}")
                )
                repo = repo_result.scalars().first()
                if repo:
                    conventions = await knowledge_store.load_or_generate_conventions(
                        repo.id, "."
                    )
                    rules = await knowledge_store.load_rules(repo.id)

            await emitter.emit("retrieving_repository_knowledge", "completed")
            await emitter.emit("loading_repository_rules", "completed")
        except Exception as e:
            logger.warning(f"Knowledge retrieval failed: {e}")
            await emitter.emit("retrieving_repository_knowledge", "failed",
                             EventType.STAGE_FAILED, message=str(e))

        return conventions, rules, repo.id if repo else None

    async def _stage_retrieval(self, emitter, index, diff_content, repo_id=None, budget=16000):
        """Stage: Context retrieval."""
        await emitter.emit("finding_related_files", "running", EventType.STAGE_START)

        if not index:
            await emitter.emit("finding_related_files", "skipped", EventType.STAGE_SKIPPED)
            return None

        try:
            import re
            changed_files = list(set(re.findall(r"diff --git a/(.*?) b/", diff_content)))

            config = RetrievalConfig(budget=budget)
            retrieval_engine.configure(config)

            retrieval_result = await retrieval_engine.retrieve(
                changed_files, ".", index, diff_content
            )

            await emitter.emit("finding_related_files", "completed",
                             metrics={"total_tokens": retrieval_result.total_tokens,
                                      "fallback": retrieval_result.fallback_used})
            await emitter.emit("ranking_context", "completed")
            await emitter.emit("compressing_context", "completed")
            return retrieval_result
        except Exception as e:
            logger.warning(f"Context retrieval failed: {e}")
            await emitter.emit("finding_related_files", "failed", EventType.STAGE_FAILED,
                             message=str(e))
            return None

    async def _stage_prompt(self, emitter, intelligence_data, conventions, rules,
                           diff_content, retrieval_result, provider="gemini"):
        """Stage: Prompt building."""
        await emitter.emit("building_prompt", "running", EventType.STAGE_START)

        try:
            prompt = await prompt_builder.compile(
                review_type=ReviewType.PR_REVIEW,
                repo_path=".",
                diff_content=sanitize_input(diff_content),
                retrieval_result=retrieval_result,
                intelligence_data=intelligence_data or {},
                conventions=conventions or "",
                rules=rules or [],
                provider=provider,
            )

            await emitter.emit("building_prompt", "completed",
                             metrics={"tokens": prompt.total_tokens})
            return prompt
        except Exception as e:
            logger.warning(f"Prompt building failed: {e}")
            await emitter.emit("building_prompt", "failed", EventType.STAGE_FAILED,
                             message=str(e))
            raise  # This is critical - cannot proceed without prompt

    async def _stage_llm(self, emitter, prompt, user_id, provider, model, api_key_id=None):
        """Stage: LLM call."""
        await emitter.emit("selecting_ai_provider", "running", EventType.STAGE_START)

        try:
            llm_response = await llm_orchestrator.complete(
                prompt=prompt,
                user_id=user_id,
                preferred_provider=provider,
                preferred_model=model,
                api_key_id=api_key_id,
                callback=emitter.emit,
            )
            await emitter.emit("receiving_ai_response", "completed", metrics={
                "provider": llm_response.provider,
                "model": llm_response.model,
                "tokens": llm_response.input_tokens + llm_response.output_tokens,
            })
            return llm_response
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            await emitter.emit("selecting_ai_provider", "failed", EventType.STAGE_FAILED,
                             message=str(e))
            raise  # This is critical - cannot proceed without LLM response

    async def _stage_verification(self, emitter, ai_response, repo_path, diff_content, review_id=None):
        """Stage: Verification."""
        await emitter.emit("running_verification_agent", "running", EventType.STAGE_START)

        try:
            import re
            changed_files = list(set(re.findall(r"diff --git a/(.*?) b/", diff_content)))
            verified = await verification_engine.verify(ai_response, repo_path, changed_files, context={"review_id": review_id})
            await emitter.emit("removing_hallucinations", "completed")
            await emitter.emit("deduplicating_findings", "completed")
            await emitter.emit("ranking_severity", "completed")
            await emitter.emit("running_verification_agent", "completed",
                             metrics=verified.to_dict())
            return verified
        except Exception as e:
            logger.warning(f"Verification failed: {e}")
            await emitter.emit("running_verification_agent", "failed",
                             EventType.STAGE_FAILED, message=str(e))
            # Return a minimal verification result
            from app.verification.models import VerificationResult
            return VerificationResult(findings=[], verified_count=0, rejected_count=0)

    async def _stage_publish(self, emitter, verified, pr_title, installation_id,
                            owner, repo_name, pr_number, intelligence_data,
                            llm_response, start):
        """Stage: Generate and publish review."""
        await emitter.emit("generating_review_summary", "running", EventType.STAGE_START)

        try:
            usage_stats = llm_orchestrator.get_total_usage()
            review_summary = await github_review_generator.generate(
                verified=verified,
                pr_title=pr_title,
                repo_summary=str(intelligence_data),
                usage_stats=usage_stats,
                duration_ms=(time.time() - start) * 1000,
            )
            await emitter.emit("generating_review_summary", "completed")
            await emitter.emit("formatting_github_review", "completed")

            # Publish to GitHub
            await emitter.emit("publishing_review", "running", EventType.STAGE_START)
            try:
                github_comments = [
                    {"path": c.path, "body": c.body, "line": c.line}
                    for c in review_summary.comments if c.line
                ]
                await github_client.create_pr_review(
                    installation_id=installation_id,
                    owner=owner,
                    repo=repo_name,
                    pull_number=pr_number,
                    body=review_summary.body,
                    event=review_summary.event,
                    comments=github_comments if github_comments else None,
                )
                await emitter.emit("publishing_review", "completed")
            except Exception as e:
                logger.error(f"Failed to publish review to GitHub: {e}")
                if github_comments:
                    logger.info("Attempting to publish review without inline comments as fallback")
                    try:
                        fallback_body = review_summary.body + "\n\n> Note: Some inline comments were omitted because they referenced unmodified lines."
                        await github_client.create_pr_review(
                            installation_id=installation_id,
                            owner=owner,
                            repo=repo_name,
                            pull_number=pr_number,
                            body=fallback_body,
                            event=review_summary.event,
                            comments=None,
                        )
                        await emitter.emit("publishing_review", "completed")
                    except Exception as fallback_e:
                        logger.error(f"Fallback publish also failed: {fallback_e}")
                        await emitter.emit("publishing_review", "failed", EventType.STAGE_FAILED, message=str(fallback_e))
                        raise fallback_e
                else:
                    await emitter.emit("publishing_review", "failed", EventType.STAGE_FAILED, message=str(e))
                    raise e

        except Exception as e:
            logger.warning(f"Review generation failed: {e}")
            await emitter.emit("generating_review_summary", "failed",
                             EventType.STAGE_FAILED, message=str(e))
            return None
            
        return review_summary.body

    async def _save_completed(self, review_id, verified, llm_response, metrics, start, user_id=None, review_summary_body=None, api_key_id=None):
        """Save completed review to database and record usage stats."""
        # --- 1. Save review status (own session) ---
        try:
            async with AsyncSessionLocal() as db:
                res = await db.execute(select(Review).where(Review.id == review_id))
                db_review = res.scalars().first()
                if db_review:
                    db_review.status = "completed"
                    db_review.completed_at = datetime.now(timezone.utc)
                    if review_summary_body:
                        db_review.summary = review_summary_body
                    db_review.stats = {
                        "provider": llm_response.provider,
                        "model": llm_response.model,
                        "verified_findings": verified.verified_count,
                        "rejected_findings": verified.rejected_count,
                        **metrics,
                    }
                    await db.commit()
        except Exception as e:
            logger.error(f"Failed to save review status: {e}")

        # --- 2. Record usage in a FRESH session ---
        try:
            from app.services.token_manager import token_manager
            from app.services.usage_tracker import usage_tracker
            import uuid as _uuid

            input_tok  = llm_response.input_tokens  or 0
            output_tok = llm_response.output_tokens or 0

            logger.info(f"[usage] Logging for review {review_id}: provider={llm_response.provider} "
                        f"input={input_tok} output={output_tok} user_id={user_id}")

            COST_TABLE = {
                "gemini":    {"input": 0.000075, "output": 0.0003},
                "openai":    {"input": 0.0025,   "output": 0.01},
                "anthropic": {"input": 0.003,    "output": 0.015},
                "deepseek":  {"input": 0.00014,  "output": 0.00028},
                "groq":      {"input": 0.00059,  "output": 0.00079},
            }
            rates = COST_TABLE.get(llm_response.provider, {"input": 0.001, "output": 0.003})
            input_cost  = round((input_tok  * rates["input"])  / 1000, 8)
            output_cost = round((output_tok * rates["output"]) / 1000, 8)

            parsed_user_id = None
            if user_id:
                try:
                    parsed_user_id = _uuid.UUID(user_id) if isinstance(user_id, str) else user_id
                except Exception:
                    pass

            if parsed_user_id:
                async with AsyncSessionLocal() as usage_db:
                    await token_manager.record_usage(
                        db=usage_db,
                        user_id=parsed_user_id,
                        provider=llm_response.provider,
                        model=llm_response.model,
                        input_tokens=input_tok,
                        output_tokens=output_tok,
                        input_cost_usd=input_cost,
                        output_cost_usd=output_cost,
                        feature="code_review",
                        latency_ms=llm_response.latency_ms or 0.0,
                        is_fallback=llm_response.is_fallback,
                        review_id=review_id,
                        api_key_id=api_key_id,
                    )
                    logger.info(f"[usage] token_manager.record_usage committed for review {review_id}")

                async with AsyncSessionLocal() as log_db:
                    await usage_tracker.log_request(
                        db=log_db,
                        request_id=str(_uuid.uuid4()),
                        user_id=parsed_user_id,
                        provider=llm_response.provider,
                        model=llm_response.model,
                        feature="code_review",
                        messages=[],
                        status="success",
                        latency_ms=llm_response.latency_ms or 0.0,
                        input_tokens=input_tok,
                        output_tokens=output_tok,
                        cost_usd=input_cost + output_cost,
                        started_at=datetime.now(timezone.utc),
                        was_fallback=llm_response.is_fallback,
                        api_key_id=api_key_id,
                        review_id=review_id,
                    )
                    logger.info(f"[usage] usage_tracker.log_request committed for review {review_id}")
            else:
                logger.warning(f"[usage] No valid user_id for review {review_id}, skipping usage log")
        except Exception as ue:
            logger.error(f"[usage] Failed to record usage stats: {ue}", exc_info=True)


    async def _save_failed(self, review_id, error_message):
        """Save failed review to database."""
        try:
            async with AsyncSessionLocal() as db:
                res = await db.execute(select(Review).where(Review.id == review_id))
                db_review = res.scalars().first()
                if db_review:
                    db_review.status = "failed"
                    db_review.error_message = error_message
                    db_review.completed_at = datetime.now(timezone.utc)
                    await db.commit()
        except Exception as e:
            logger.error(f"Failed to save failed review: {e}")


review_pipeline = ReviewPipeline()
