
from app.retrieval.models import RetrievedContext


def rank_context(
    contexts: list[RetrievedContext],
    max_files: int = 10,
) -> list[RetrievedContext]:
    scored = sorted(contexts, key=lambda c: c.relevance_score, reverse=True)
    return scored[:max_files]


def deduplicate_context(contexts: list[RetrievedContext]) -> list[RetrievedContext]:
    seen_paths: set = set()
    unique: list[RetrievedContext] = []

    for ctx in contexts:
        if ctx.file_path not in seen_paths:
            seen_paths.add(ctx.file_path)
            unique.append(ctx)

    return unique


def merge_contexts(
    import_contexts: list[RetrievedContext],
    call_contexts: list[RetrievedContext],
    test_contexts: list[RetrievedContext],
    max_total: int = 10,
) -> list[RetrievedContext]:
    all_contexts = import_contexts + call_contexts + test_contexts
    deduplicated = deduplicate_context(all_contexts)
    ranked = rank_context(deduplicated, max_files=max_total)
    return ranked
