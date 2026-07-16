"""Production-grade Prompt Builder Engine.

Orchestrates prompt construction from context retrieval results through
section building, ranking, compression, optimization, validation, and caching.
"""

import time
import logging
import hashlib
import uuid
from typing import Dict, Optional

from app.prompt_engine.models import (
    CompiledPrompt, PromptSection, PromptBuildRequest,
    ReviewType, RepositorySize, TokenMetadata, ProviderMetadata,
    PromptExplainability,
)
from app.prompt_engine.section_builders import ALL_SECTION_BUILDERS
from app.prompt_engine.context_ranker import ContextRanker
from app.prompt_engine.token_budget import PromptTokenBudget, estimate_tokens
from app.prompt_engine.optimizer import PromptOptimizer
from app.prompt_engine.compressor import PromptCompressor
from app.prompt_engine.validator import PromptValidator
from app.prompt_engine.cache import PromptCache, build_cache_key
from app.prompt_engine.versioning import PromptVersionManager
from app.prompt_engine.observability import PromptObservability

logger = logging.getLogger(__name__)

# All valid PromptBuildRequest field names
_PROMPT_BUILD_REQUEST_FIELDS = {
    "review_type", "repo_id", "repo_path", "repo_size", "diff_content",
    "retrieval_result", "intelligence_data", "conventions", "rules",
    "static_analysis", "provider", "model", "token_budget", "pr_number",
    "pr_title", "pr_description", "issue_context", "organization_rules",
    "enable_caching", "enable_compression", "enable_versioning",
}


class PromptBuilder:
    """Production-grade Prompt Builder Engine.

    Sits between Context Retrieval Engine and LLM Orchestrator.
    Transforms retrieval results into optimized prompts for any review type.
    """

    def __init__(self):
        self.section_builders = ALL_SECTION_BUILDERS
        self.ranker = ContextRanker()
        self.optimizer = PromptOptimizer()
        self.compressor = PromptCompressor()
        self.validator = PromptValidator()
        self.cache = PromptCache()
        self.version_manager = PromptVersionManager()
        self.observability = PromptObservability()

    async def compile(self, **kwargs) -> CompiledPrompt:
        """Main entry point. Backward-compatible with existing pipeline call.

        Accepts both the new PromptBuildRequest fields and legacy kwargs
        (repo_summary, architecture_summary, etc.) for backward compatibility.
        """
        start = time.time()

        request = self._parse_request(**kwargs)

        cache_key = self._build_cache_key(request)
        if request.enable_caching:
            cached = await self.cache.get(cache_key)
            if cached:
                logger.info(f"Cache hit for prompt {cached.prompt_id}")
                await self.observability.record_build(cached, request, 0, cache_hit=True)
                return cached

        ranked = await self.ranker.rank_contexts(
            request.retrieval_result, request.token_budget
        )

        budget_manager = PromptTokenBudget(request.repo_size, request.token_budget)

        sections = {}
        for builder in self.section_builders:
            section = await builder.safe_build(request, {"ranked_context": ranked})
            if section:
                sections[section.name] = section

        if request.enable_compression:
            sections = await self.compressor.compress_sections(sections, request.token_budget)

        sections = await self.optimizer.optimize(sections, budget_manager)

        system_section = sections.pop("system_instructions", None)
        system_prompt = system_section.content if system_section else ""

        priority_order = [
            "repository_summary", "architecture_summary", "repository_rules",
            "coding_conventions", "organization_rules", "relevant_files",
            "relevant_code", "static_analysis", "review_context",
            "issue_context", "output_format",
        ]

        user_parts = []
        for name in priority_order:
            if name in sections:
                section = sections[name]
                display_name = name.replace("_", " ").title()
                user_parts.append(f"## {display_name}\n\n{section.content}")

        user_prompt = "\n\n".join(user_parts)

        total_tokens = estimate_tokens(system_prompt + user_prompt)

        prompt_id = self._generate_id(request)
        token_metadata = budget_manager.build_token_metadata()
        token_metadata.total_tokens = total_tokens
        token_metadata.compression_ratio = self._calculate_compression_ratio(sections)

        provider_metadata = ProviderMetadata(
            provider=request.provider,
            model=request.model,
        )

        explainability = self._build_explainability(
            sections, request, total_tokens, ranked.files_count
        )

        prompt = CompiledPrompt(
            version="2.0",
            prompt_id=prompt_id,
            prompt_version="2.0",
            review_type=request.review_type.value,
            sections=sections,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            total_tokens=total_tokens,
            cache_key=cache_key,
            token_metadata=token_metadata,
            provider_metadata=provider_metadata,
            explainability=explainability,
            created_at=time.time(),
            build_time_ms=(time.time() - start) * 1000,
        )

        validation = await self.validator.validate(prompt, request)
        if not validation.valid:
            logger.warning(f"Prompt validation issues: {validation.errors}")

        if request.enable_caching:
            await self.cache.set(cache_key, prompt)

        if request.enable_versioning:
            await self.version_manager.register_version(
                f"{request.review_type.value}:{request.repo_id}",
                "2.0",
                prompt,
            )

        await self.observability.record_build(prompt, request, prompt.build_time_ms)

        logger.info(
            f"Built prompt {prompt_id}: {total_tokens} tokens "
            f"in {prompt.build_time_ms:.1f}ms "
            f"({len(sections)} sections, review_type={request.review_type.value})"
        )

        return prompt

    def _parse_request(self, **kwargs) -> PromptBuildRequest:
        """Convert legacy compile() kwargs to PromptBuildRequest.

        Supports both the new structured interface and the legacy
        flat parameter interface for backward compatibility.
        """
        if "review_type" in kwargs and isinstance(kwargs["review_type"], ReviewType):
            # New interface: filter to only PromptBuildRequest fields
            filtered = {k: v for k, v in kwargs.items() if k in _PROMPT_BUILD_REQUEST_FIELDS}
            return PromptBuildRequest(**filtered)

        request = PromptBuildRequest()

        if "repo_summary" in kwargs:
            request.intelligence_data = {"summary": kwargs["repo_summary"]}
        if "architecture_summary" in kwargs:
            if request.intelligence_data:
                request.intelligence_data["architecture"] = {"pattern": kwargs["architecture_summary"]}
            else:
                request.intelligence_data = {"architecture": {"pattern": kwargs["architecture_summary"]}}
        if "intelligence_data" in kwargs:
            request.intelligence_data = kwargs["intelligence_data"]
        if "conventions" in kwargs:
            request.conventions = kwargs["conventions"]
        if "rules" in kwargs:
            request.rules = kwargs["rules"] or []
        if "diff_content" in kwargs:
            request.diff_content = kwargs["diff_content"]
        if "related_files" in kwargs:
            pass
        if "static_analysis" in kwargs:
            request.static_analysis = kwargs["static_analysis"]

        for key in ["review_type", "repo_id", "repo_path", "repo_size", "provider",
                     "model", "token_budget", "pr_number", "pr_title", "pr_description",
                     "issue_context", "organization_rules", "enable_caching",
                     "enable_compression", "enable_versioning", "retrieval_result"]:
            if key in kwargs:
                setattr(request, key, kwargs[key])

        return request

    def _build_cache_key(self, request: PromptBuildRequest) -> str:
        """Build a deterministic cache key."""
        diff_hash = hashlib.sha256(request.diff_content.encode()).hexdigest()[:8] if request.diff_content else "none"
        return build_cache_key(
            review_type=request.review_type.value,
            repo_id=request.repo_id or "unknown",
            diff_content=diff_hash,
            provider=request.provider,
            model=request.model,
            token_budget=request.token_budget,
        )

    def _generate_id(self, request: PromptBuildRequest) -> str:
        """Generate a unique prompt ID."""
        timestamp = int(time.time() * 1000)
        unique = uuid.uuid4().hex[:8]
        return f"prompt_{timestamp}_{unique}"

    def _calculate_compression_ratio(self, sections: Dict[str, PromptSection]) -> float:
        """Calculate the compression ratio from section metadata.

        Returns 0.0 when no sections are compressed, 1.0 when all are compressed.
        """
        compressed_count = sum(1 for s in sections.values() if s.compressed)
        total_count = len(sections)
        if total_count == 0:
            return 0.0
        return compressed_count / total_count

    def _build_explainability(
        self,
        sections: Dict[str, PromptSection],
        request: PromptBuildRequest,
        total_tokens: int,
        files_count: int,
    ) -> PromptExplainability:
        """Build user-facing explainability metadata."""
        return PromptExplainability(
            prompt_version="2.0",
            tokens_used=total_tokens,
            context_size=sum(s.token_count for s in sections.values()),
            files_retrieved=files_count,
            compression_ratio=self._calculate_compression_ratio(sections),
            selected_provider=request.provider,
            selected_model=request.model,
            review_type=request.review_type.value,
            sections_included=list(sections.keys()),
            budget_allocation={name: s.token_count for name, s in sections.items()},
        )


prompt_builder = PromptBuilder()
