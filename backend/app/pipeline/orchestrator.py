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
from app.prompt_engine.builder import prompt_builder
from app.orchestrator.orchestrator import llm_orchestrator
from app.verification.engine import verification_engine
from app.github_review.generator import github_review_generator
from app.security.sanitizer import sanitize_content
from app.github.client import github_client
from app.ai.git_utils import GitService

logger = logging.getLogger(__name__)


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

        try:
            # Stage 1: Prepare
            await emitter.emit("preparing_review", "running", EventType.STAGE_START)
            await emitter.emit_log("preparing_review", f"Starting review for PR #{pr_number}")

            # Stage 2: Clone repository
            repo_path = await self._stage_clone(emitter, clone_url, token)

            # Stage 3: Intelligence analysis (if cloned)
            intelligence_data = await self._stage_intelligence(emitter, repo_path)

            # Stage 4: Indexing (if cloned)
            index = await self._stage_indexing(emitter, repo_path)

            # Cleanup cloned repo immediately after indexing
            if repo_path:
                GitService.cleanup_repository(repo_path)
                repo_path = None

            # Stage 5: Knowledge retrieval
            conventions, rules = await self._stage_knowledge(
                emitter, owner, repo_name
            )

            # Stage 6: Context retrieval
            retrieval_result = await self._stage_retrieval(
                emitter, index, diff_content
            )

            # Stage 7: Build prompt
            prompt = await self._stage_prompt(
                emitter, intelligence_data, conventions, rules,
                diff_content, retrieval_result
            )

            # Stage 8: LLM call
            llm_response = await self._stage_llm(
                emitter, prompt, user_id, provider, model
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
                emitter, llm_response.content, repo_path or ".", diff_content
            )

            # Stage 10: Generate and publish review
            await self._stage_publish(
                emitter, verified, pr_title, installation_id,
                owner, repo_name, pr_number, intelligence_data,
                llm_response, start
            )

            # Save to DB
            await self._save_completed(
                review_id, verified, llm_response, metrics, start
            )

            # Complete
            duration_ms = (time.time() - start) * 1000
            await emitter.emit("completed", "completed", EventType.REVIEW_COMPLETE, metrics={
                "duration_ms": duration_ms,
                **metrics,
            })

            return {"status": "success", "duration_ms": duration_ms, "metrics": metrics}

        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            await emitter.emit_error("pipeline", str(e))

            # Mark review as failed
            await self._save_failed(review_id, str(e))

            return {"status": "failed", "error": str(e)}

        finally:
            # Ensure repo cleanup
            if repo_path:
                try:
                    GitService.cleanup_repository(repo_path)
                except Exception as e:
                    logger.warning(f"Failed to cleanup repo: {e}")

    async def _stage_clone(self, emitter, clone_url, token):
        """Stage: Clone repository."""
        await emitter.emit("cloning_repository", "running", EventType.STAGE_START)

        if not clone_url or not token:
            await emitter.emit("cloning_repository", "skipped", EventType.STAGE_SKIPPED,
                             message="No clone URL provided")
            return None

        try:
            repo_path = GitService.clone_repository(clone_url, token)
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

    async def _stage_indexing(self, emitter, repo_path):
        """Stage: Code graph indexing."""
        if not repo_path:
            await emitter.emit("indexing_repository", "skipped", EventType.STAGE_SKIPPED)
            return None

        await emitter.emit("indexing_repository", "running", EventType.STAGE_START)

        try:
            index = await repository_indexer.build_index(repo_path)
            await emitter.emit("building_dependency_graph", "completed")
            await emitter.emit("building_call_graph", "completed")
            await emitter.emit("building_import_graph", "completed")
            await emitter.emit("building_ast", "completed")
            await emitter.emit("indexing_repository", "completed", EventType.STAGE_COMPLETE)
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

        return conventions, rules

    async def _stage_retrieval(self, emitter, index, diff_content):
        """Stage: Context retrieval."""
        await emitter.emit("finding_related_files", "running", EventType.STAGE_START)

        if not index:
            await emitter.emit("finding_related_files", "skipped", EventType.STAGE_SKIPPED)
            return None

        try:
            import re
            changed_files = list(set(re.findall(r"diff --git a/(.*?) b/", diff_content)))
            retrieval_result = await retrieval_engine.retrieve(
                changed_files, ".", index, diff_content
            )
            await emitter.emit("finding_related_files", "completed")
            await emitter.emit("ranking_context", "completed")
            await emitter.emit("compressing_context", "completed")
            return retrieval_result
        except Exception as e:
            logger.warning(f"Context retrieval failed: {e}")
            await emitter.emit("finding_related_files", "failed", EventType.STAGE_FAILED,
                             message=str(e))
            return None

    async def _stage_prompt(self, emitter, intelligence_data, conventions, rules,
                           diff_content, retrieval_result):
        """Stage: Prompt building."""
        await emitter.emit("building_prompt", "running", EventType.STAGE_START)

        try:
            related_files_data = []
            if retrieval_result:
                related_files_data = [
                    {"file_path": r.file_path, "content": r.content[:1000]}
                    for r in retrieval_result.related_files
                ]

            prompt = await prompt_builder.compile(
                repo_summary=str(intelligence_data),
                architecture_summary=intelligence_data.get("architecture", {}).get("pattern", "")
                    if intelligence_data else "",
                conventions=conventions,
                rules=rules,
                diff_content=sanitize_content(diff_content),
                related_files=related_files_data,
            )

            await emitter.emit("building_prompt", "completed",
                             metrics={"tokens": prompt.total_tokens})
            return prompt
        except Exception as e:
            logger.warning(f"Prompt building failed: {e}")
            await emitter.emit("building_prompt", "failed", EventType.STAGE_FAILED,
                             message=str(e))
            raise  # This is critical - cannot proceed without prompt

    async def _stage_llm(self, emitter, prompt, user_id, provider, model):
        """Stage: LLM call."""
        await emitter.emit("selecting_ai_provider", "running", EventType.STAGE_START)

        try:
            llm_response = await llm_orchestrator.complete(
                prompt=prompt,
                user_id=user_id,
                preferred_provider=provider,
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

    async def _stage_verification(self, emitter, ai_response, repo_path, diff_content):
        """Stage: Verification."""
        await emitter.emit("running_verification_agent", "running", EventType.STAGE_START)

        try:
            import re
            changed_files = list(set(re.findall(r"diff --git a/(.*?) b/", diff_content)))
            verified = await verification_engine.verify(ai_response, repo_path, changed_files)
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
                await emitter.emit("publishing_review", "failed", EventType.STAGE_FAILED,
                                 message=str(e))

        except Exception as e:
            logger.warning(f"Review generation failed: {e}")
            await emitter.emit("generating_review_summary", "failed",
                             EventType.STAGE_FAILED, message=str(e))

    async def _save_completed(self, review_id, verified, llm_response, metrics, start):
        """Save completed review to database."""
        try:
            async with AsyncSessionLocal() as db:
                res = await db.execute(select(Review).where(Review.id == review_id))
                db_review = res.scalars().first()
                if db_review:
                    db_review.status = "completed"
                    db_review.completed_at = datetime.now(timezone.utc)
                    db_review.stats = {
                        "provider": llm_response.provider,
                        "model": llm_response.model,
                        "verified_findings": verified.verified_count,
                        **metrics,
                    }
                    await db.commit()
        except Exception as e:
            logger.error(f"Failed to save review: {e}")

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
