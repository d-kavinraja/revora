import time
import hashlib
import logging
import asyncio
from typing import List, Optional

from app.retrieval.models import RetrievalResult, RetrievedContext, RetrievalConfig
from app.retrieval.fallback import retrieval_fallback, RetrievalFallback
from app.cache.memory_cache import memory_cache
from app.cache.redis_cache import redis_cache
from app.indexing.models import RepositoryIndex

logger = logging.getLogger(__name__)


class RetrievalEngine:
    def __init__(self, config: Optional[RetrievalConfig] = None):
        self._config = config or RetrievalConfig()
        self._retrievers: list = []
        self._ranking_engine = None
        self._compression_engine = None

    def configure(self, config: RetrievalConfig) -> None:
        self._config = config
        logger.info(f"RetrievalEngine configured: budget={config.budget}, "
                     f"ranking={config.enable_ranking}, compression={config.enable_compression}, "
                     f"cache={config.enable_cache}, fallback={config.enable_fallback}")

    def register_retriever(self, retriever) -> None:
        self._retrievers.append(retriever)
        logger.info(f"Registered retriever: {retriever.name}")

    def set_ranking_engine(self, engine) -> None:
        self._ranking_engine = engine

    def set_compression_engine(self, engine) -> None:
        self._compression_engine = engine

    async def retrieve(
        self,
        changed_files: List[str],
        repo_path: str,
        index: Optional[RepositoryIndex] = None,
        diff_content: Optional[str] = None,
    ) -> RetrievalResult:
        start = time.time()
        retrieval_fallback.reset()

        logger.info(
            f"Retrieving context for {len(changed_files)} changed files, "
            f"budget={self._config.budget}"
        )

        result = RetrievalResult()
        result.budget_limit = self._config.budget

        cache_key = self._build_cache_key(repo_path, changed_files, diff_content)

        if self._config.enable_cache:
            cached = await self._try_cache(cache_key)
            if cached is not None:
                logger.info(f"Cache hit for {cache_key}")
                return cached

        result._changed_file_paths = changed_files
        result._repo_path = repo_path
        result._index = index
        result._diff_content = diff_content

        if index is not None and self._config.enable_graph_traversal:
            await self._execute_with_graph(result, index)
        else:
            await self._execute_without_graph(result)

        if retrieval_fallback.is_failed():
            logger.warning("All retrieval strategies failed, returning minimal result")
            result.fallback_used = "graceful_failure"
        elif retrieval_fallback.current_strategy != "graph_retrieval":
            result.fallback_used = retrieval_fallback.current_strategy

        if self._config.enable_ranking and self._ranking_engine and not retrieval_fallback.is_failed():
            try:
                ranked = await self._ranking_engine.rank(result.all_contexts())
                self._apply_ranked(result, ranked)
            except Exception as e:
                logger.warning(f"Ranking failed: {e}")

        if self._config.enable_compression and self._compression_engine and not retrieval_fallback.is_failed():
            try:
                await self._compression_engine.compress(result, self._config.budget)
            except Exception as e:
                logger.warning(f"Compression failed: {e}")

        self._calculate_tokens(result)

        if self._config.enable_cache:
            await self._store_cache(cache_key, result)

        result.retrieval_time_ms = (time.time() - start) * 1000
        logger.info(
            f"Retrieval completed in {result.retrieval_time_ms:.0f}ms — "
            f"{result.total_tokens} tokens, "
            f"fallback={result.fallback_used or 'none'}"
        )

        return result

    async def _execute_with_graph(self, result: RetrievalResult, index: RepositoryIndex) -> None:
        if self._retrievers:
            tasks = []
            for retriever in self._retrievers:
                task = retriever.safe_retrieve(self._config, result)
                tasks.append(task)

            all_results = await asyncio.gather(*tasks, return_exceptions=True)

            for retriever_results in all_results:
                if isinstance(retriever_results, Exception):
                    logger.warning(f"Retriever raised exception: {retriever_results}")
                    continue
                if not retriever_results:
                    continue
                for ctx in retriever_results:
                    self._assign_to_result(result, ctx)
        else:
            self._fallback_to_basic(result)

    async def _execute_without_graph(self, result: RetrievalResult) -> None:
        if retrieval_fallback.should_use_graph():
            retrieval_fallback.escalate()

        if retrieval_fallback.should_use_knowledge_base():
            self._fallback_to_basic(result)
            retrieval_fallback.escalate()
        elif retrieval_fallback.should_use_static_analysis():
            self._fallback_to_basic(result)
            retrieval_fallback.escalate()

    def _fallback_to_basic(self, result: RetrievalResult) -> None:
        from app.retrieval.file_retriever import (
            get_related_files_from_imports,
            get_related_files_from_calls,
            get_test_files,
            read_file_content,
        )

        repo_path = getattr(result, "_repo_path", ".")
        index = getattr(result, "_index", None)
        changed_files = getattr(result, "_changed_file_paths", [])

        for fp in changed_files:
            content = read_file_content(repo_path, fp)
            if content:
                result.changed_files.append(RetrievedContext(
                    file_path=fp,
                    content=content,
                    relevance_score=1.0,
                    source="changed_file",
                    metadata={"tokens": len(content) // 4},
                ))

        if index:
            import_related = get_related_files_from_imports(
                changed_files,
                index.import_graph.nodes,
                index.import_graph.edges,
                repo_path,
            )
            call_related = get_related_files_from_calls(
                changed_files,
                index.call_graph.nodes,
                index.call_graph.edges,
                repo_path,
            )
            test_files = get_test_files(
                changed_files,
                index.test_graph.nodes,
                index.test_graph.edges,
                repo_path,
            )
            result.related_files.extend(import_related)
            result.related_files.extend(call_related)
            result.test_files.extend(test_files)

    def _assign_to_result(self, result: RetrievalResult, ctx: RetrievedContext) -> None:
        source_group = ctx.source
        if source_group == "changed_file":
            result.changed_files.append(ctx)
        elif source_group in ("test_graph", "test_file"):
            result.test_files.append(ctx)
        elif source_group == "config":
            result.config_files.append(ctx)
        elif source_group == "api_endpoint":
            result.api_endpoints.append(ctx)
        elif source_group == "db_schema":
            result.db_schemas.append(ctx)
        elif source_group == "security":
            result.security_context.append(ctx)
        elif source_group == "impact":
            result.impact_context.append(ctx)
        elif source_group == "historical":
            result.historical_context.append(ctx)
        elif source_group == "rule":
            result.rule_context.append(ctx)
        elif source_group == "documentation":
            result.documentation_context.append(ctx)
        else:
            result.related_files.append(ctx)

    def _apply_ranked(self, result: RetrievalResult, ranked: list[RetrievedContext]) -> None:
        result.related_files.clear()
        result.test_files.clear()
        result.api_endpoints.clear()
        result.db_schemas.clear()
        result.security_context.clear()
        result.impact_context.clear()
        result.historical_context.clear()
        result.rule_context.clear()
        result.documentation_context.clear()

        for ctx in ranked:
            self._assign_to_result(result, ctx)

    def _calculate_tokens(self, result: RetrievalResult) -> None:
        total = 0
        for ctx in result.all_contexts():
            total += len(ctx.content) // 4
        result.total_tokens = total
        result.budget_used = round(total / max(result.budget_limit, 1), 2)

    def _build_cache_key(self, repo_path: str, changed_files: list[str], diff_content: Optional[str] = None) -> str:
        raw = f"{repo_path}:{sorted(changed_files)}:{diff_content or ''}:{self._config.budget}"
        return f"retrieval:{hashlib.sha256(raw.encode()).hexdigest()[:32]}"

    async def _try_cache(self, key: str) -> Optional[RetrievalResult]:
        cached = await redis_cache.get(key)
        if cached is not None:
            if isinstance(cached, dict):
                result = RetrievalResult(**{k: v for k, v in cached.items() if k != "changed_files"})
                result.cache_hit = True
                return result
            if isinstance(cached, RetrievalResult):
                cached.cache_hit = True
                return cached
        return None

    async def _store_cache(self, key: str, result: RetrievalResult) -> None:
        ttl = self._config.cache_ttl_seconds
        try:
            await redis_cache.set(key, result.to_dict(), ttl)
        except Exception as e:
            logger.debug(f"Failed to cache retrieval result: {e}")


retrieval_engine = RetrievalEngine()
