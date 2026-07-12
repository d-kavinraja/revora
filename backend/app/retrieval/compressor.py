from app.retrieval.models import RetrievedContext
from app.retrieval.token_budget import truncate_to_budget, estimate_tokens


def compress_context(
    contexts: list[RetrievedContext],
    max_tokens_per_file: int = 500,
) -> list[RetrievedContext]:
    compressed = []
    for ctx in contexts:
        tokens = estimate_tokens(ctx.content)
        if tokens > max_tokens_per_file:
            truncated = truncate_to_budget(ctx.content, max_tokens_per_file)
            compressed.append(RetrievedContext(
                file_path=ctx.file_path,
                content=truncated,
                relevance_score=ctx.relevance_score,
                source=ctx.source,
                metadata={**ctx.metadata, "compressed": True, "original_tokens": tokens},
            ))
        else:
            compressed.append(ctx)
    return compressed


def compress_changed_files(
    file_contents: dict[str, str],
    patch: str,
    max_patch_tokens: int = 1500,
) -> str:
    tokens = estimate_tokens(patch)
    if tokens <= max_patch_tokens:
        return patch
    return truncate_to_budget(patch, max_patch_tokens)
