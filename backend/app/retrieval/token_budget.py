TOTAL_BUDGET = 10000

ALLOCATION = {
    "system": 500,
    "repo_summary": 300,
    "architecture": 300,
    "rules": 200,
    "changed_files": 3000,
    "related_context": 4000,
    "static_analysis": 500,
    "output_buffer": 1200,
}


def estimate_tokens(text: str) -> int:
    """Rough token estimation: ~4 chars per token for English."""
    return max(1, len(text) // 4)


def get_available_budget(used_sections: dict[str, int]) -> int:
    used = sum(used_sections.values())
    return max(0, TOTAL_BUDGET - used)


def should_include(content: str, current_tokens: int, budget: int) -> bool:
    tokens = estimate_tokens(content)
    return (current_tokens + tokens) <= budget


def truncate_to_budget(text: str, max_tokens: int) -> str:
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_newline = truncated.rfind("\n")
    if last_newline > max_chars * 0.8:
        truncated = truncated[:last_newline]
    return truncated + "\n... [truncated]"
