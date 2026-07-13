import logging
import time
from typing import List, Optional

from app.retrieval.models import RetrievalResult, RetrievedContext
from app.retrieval.file_retriever import (
    get_related_files_from_imports,
    get_related_files_from_calls,
    get_test_files,
    read_file_content,
)
from app.retrieval.ranking import merge_contexts, deduplicate_context
from app.retrieval.compressor import compress_context
from app.retrieval.token_budget import estimate_tokens, TOTAL_BUDGET, get_available_budget, ALLOCATION
from app.indexing.models import RepositoryIndex

logger = logging.getLogger(__name__)


class RetrievalEngine:
    """Retrieves relevant context for code review based on changed files."""

    async def retrieve(
        self,
        changed_files: List[str],
        repo_path: str,
        index: RepositoryIndex,
        diff_content: Optional[str] = None,
    ) -> RetrievalResult:
        start = time.time()
        logger.info(f"Retrieving context for {len(changed_files)} changed files")

        result = RetrievalResult()
        budget_used = 0

        # 1. Read changed file contents
        for fp in changed_files:
            content = read_file_content(repo_path, fp)
            if content:
                tokens = estimate_tokens(content)
                result.changed_files.append(RetrievedContext(
                    file_path=fp,
                    content=content,
                    relevance_score=1.0,
                    source="changed_file",
                    metadata={"tokens": tokens},
                ))
                budget_used += tokens

        # 2. Get related files from import graph
        import_related = get_related_files_from_imports(
            changed_files,
            index.import_graph.nodes,
            index.import_graph.edges,
            repo_path,
        )

        # 3. Get related files from call graph
        call_related = get_related_files_from_calls(
            changed_files,
            index.call_graph.nodes,
            index.call_graph.edges,
            repo_path,
        )

        # 4. Get test files
        test_files = get_test_files(
            changed_files,
            index.test_graph.nodes,
            index.test_graph.edges,
            repo_path,
        )

        # 5. Merge and rank
        available_budget = TOTAL_BUDGET - budget_used - ALLOCATION.get("output_buffer", 1200)
        related_budget = min(available_budget, ALLOCATION.get("related_context", 4000))

        merged = merge_contexts(import_related, call_related, test_files, max_total=10)

        # 6. Compress to fit budget
        compressed = compress_context(merged, max_tokens_per_file=500)

        # 7. Fit within budget
        for ctx in compressed:
            tokens = estimate_tokens(ctx.content)
            if budget_used + tokens <= related_budget + ALLOCATION.get("output_buffer", 1200):
                result.related_files.append(ctx)
                budget_used += tokens

        result.test_files = [t for t in test_files if t.file_path not in {r.file_path for r in result.related_files}]

        # Calculate final stats
        result.total_tokens = budget_used
        result.budget_used = round(budget_used / TOTAL_BUDGET, 2)

        elapsed_ms = (time.time() - start) * 1000
        logger.info(f"Context retrieval completed in {elapsed_ms:.0f}ms — {result.total_tokens} tokens, {len(result.related_files)} related files")

        return result


retrieval_engine = RetrievalEngine()
