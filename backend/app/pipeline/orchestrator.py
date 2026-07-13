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
    """Orchestrates the full Context Engineering review pipeline."""

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
        start = time.time()
        emitter = SSEEmitter(str(review_id))
        metrics = {}

        try:
            # Stage 1: Prepare
            await emitter.emit("preparing_review", "running", EventType.STAGE_START)
            await emitter.emit_log("preparing_review", f"Starting review for PR #{pr_number}")

            # Stage 2: Clone repository
            await emitter.emit("cloning_repository", "running", EventType.STAGE_START)
            repo_path = None
            if clone_url and token:
                try:
                    repo_path = GitService.clone_repository(clone_url, token)
                    await emitter.emit("cloning_repository", "completed", EventType.STAGE_COMPLETE)
                except Exception as e:
                    await emitter.emit("cloning_repository", "failed", EventType.STAGE_FAILED, message=str(e))
                    repo_path = None
            else:
                await emitter.emit("cloning_repository", "skipped", EventType.STAGE_SKIPPED, message="No clone URL provided")

            # Stage 3: Analyze repository (if cloned)
            intelligence_data = {}
            index = None
            if repo_path:
                await emitter.emit("analyzing_repository", "running", EventType.STAGE_START)

                # Phase 1: Intelligence
                await emitter.emit("detecting_languages", "running")
                intelligence = await intelligence_engine.analyze(repo_path)
                intelligence_data = intelligence.to_dict()
                await emitter.emit("detecting_languages", "completed", metrics={"languages": len(intelligence.languages)})
                await emitter.emit("detecting_frameworks", "completed", metrics={"frameworks": len(intelligence.frameworks)})
                await emitter.emit("analyzing_architecture", "completed", metrics={"pattern": intelligence.architecture.pattern if intelligence.architecture else "unknown"})
                await emitter.emit("analyzing_repository", "completed", EventType.STAGE_COMPLETE, metrics=intelligence_data)

                # Phase 2: Indexing
                await emitter.emit("indexing_repository", "running", EventType.STAGE_START)
                index = await repository_indexer.build_index(repo_path)
                metrics["graph_stats"] = index.metadata.get("graph_stats", {})
                await emitter.emit("building_dependency_graph", "completed")
                await emitter.emit("building_call_graph", "completed")
                await emitter.emit("building_import_graph", "completed")
                await emitter.emit("building_ast", "completed")
                await emitter.emit("indexing_repository", "completed", EventType.STAGE_COMPLETE)

                # Cleanup cloned repo
                GitService.cleanup_repository(repo_path)
            else:
                await emitter.emit("analyzing_repository", "skipped", EventType.STAGE_SKIPPED)
                await emitter.emit("indexing_repository", "skipped", EventType.STAGE_SKIPPED)

            # Phase 4: Context Retrieval
            changed_files = []
            if index:
                await emitter.emit("finding_related_files", "running", EventType.STAGE_START)
                # Extract changed file paths from diff
                import re
                changed_files = list(set(re.findall(r"diff --git a/(.*?) b/", diff_content)))
                retrieval_result = await retrieval_engine.retrieve(changed_files, repo_path or ".", index, diff_content)
                metrics["files_retrieved"] = len(retrieval_result.related_files)
                metrics["total_tokens"] = retrieval_result.total_tokens
                await emitter.emit("finding_related_files", "completed")
                await emitter.emit("ranking_context", "completed")
                await emitter.emit("compressing_context", "completed")
            else:
                retrieval_result = None
                await emitter.emit("finding_related_files", "skipped", EventType.STAGE_SKIPPED)

            # Phase 3: Knowledge
            await emitter.emit("retrieving_repository_knowledge", "running", EventType.STAGE_START)
            repo_id = None
            async with AsyncSessionLocal() as db:
                repo_result = await db.execute(
                    select(Repository).where(Repository.full_name == f"{owner}/{repo_name}")
                )
                repo = repo_result.scalars().first()
                if repo:
                    repo_id = repo.id

            conventions = ""
            rules = []
            if repo_id:
                conventions = await knowledge_store.load_or_generate_conventions(repo_id, repo_path or ".")
                rules = await knowledge_store.load_rules(repo_id)
            await emitter.emit("retrieving_repository_knowledge", "completed")
            await emitter.emit("loading_repository_rules", "completed")

            # Phase 5: Build Prompt
            await emitter.emit("building_prompt", "running", EventType.STAGE_START)
            related_files_data = []
            if retrieval_result:
                related_files_data = [
                    {"file_path": r.file_path, "content": r.content[:1000]}
                    for r in retrieval_result.related_files
                ]

            prompt = await prompt_builder.compile(
                repo_summary=str(intelligence_data),
                architecture_summary=intelligence_data.get("architecture", {}).get("pattern", "") if intelligence_data else "",
                conventions=conventions,
                rules=rules,
                diff_content=sanitize_content(diff_content),
                related_files=related_files_data,
            )
            metrics["prompt_tokens"] = prompt.total_tokens
            await emitter.emit("building_prompt", "completed", metrics={"tokens": prompt.total_tokens})

            # Phase 6: LLM Call
            await emitter.emit("selecting_ai_provider", "running", EventType.STAGE_START)
            llm_response = await llm_orchestrator.complete(
                prompt=prompt,
                user_id=user_id,
                preferred_provider=provider,
                callback=emitter.emit,
            )
            metrics["provider"] = llm_response.provider
            metrics["model"] = llm_response.model
            metrics["input_tokens"] = llm_response.input_tokens
            metrics["output_tokens"] = llm_response.output_tokens
            metrics["estimated_cost"] = llm_response.estimated_cost_usd

            await emitter.emit("receiving_ai_response", "completed", metrics={
                "provider": llm_response.provider,
                "model": llm_response.model,
                "tokens": llm_response.input_tokens + llm_response.output_tokens,
            })

            # Phase 7: Verification
            await emitter.emit("running_verification_agent", "running", EventType.STAGE_START)
            verified = await verification_engine.verify(llm_response.content, repo_path or ".", changed_files)
            metrics["verified_findings"] = verified.verified_count
            metrics["rejected_findings"] = verified.rejected_count
            await emitter.emit("removing_hallucinations", "completed")
            await emitter.emit("deduplicating_findings", "completed")
            await emitter.emit("ranking_severity", "completed")
            await emitter.emit("running_verification_agent", "completed", metrics=verified.to_dict())

            # Phase 8: Generate GitHub Review
            await emitter.emit("generating_review_summary", "running", EventType.STAGE_START)
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
                await emitter.emit("publishing_review", "failed", EventType.STAGE_FAILED, message=str(e))

            # Save to DB
            async with AsyncSessionLocal() as db:
                res = await db.execute(select(Review).where(Review.id == review_id))
                db_review = res.scalars().first()
                if db_review:
                    db_review.status = "completed"
                    db_review.summary = review_summary.body
                    db_review.completed_at = datetime.now(timezone.utc)
                    db_review.stats = {
                        "provider": llm_response.provider,
                        "model": llm_response.model,
                        "risk_score": review_summary.risk_score,
                        "verified_findings": verified.verified_count,
                        **metrics,
                    }
                    await db.commit()

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
            async with AsyncSessionLocal() as db:
                res = await db.execute(select(Review).where(Review.id == review_id))
                db_review = res.scalars().first()
                if db_review:
                    db_review.status = "failed"
                    db_review.error_message = str(e)
                    db_review.completed_at = datetime.now(timezone.utc)
                    await db.commit()

            return {"status": "failed", "error": str(e)}


review_pipeline = ReviewPipeline()
