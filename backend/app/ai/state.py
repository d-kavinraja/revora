from typing import Any, TypedDict


class ReviewState(TypedDict):
    """LangGraph State for the PR Review Pipeline"""
    pr_number: int
    pr_title: str
    pr_description: str
    diff_content: str
    repo_context: dict[str, Any]
    
    # User / Auth Context
    user_id: str
    provider: str
    model: str | None
    api_key_id: str | None
    
    # Agent Outputs
    bug_analysis: list[str]
    security_analysis: list[str]
    performance_analysis: list[str]
    style_analysis: list[str]
    
    # Final Output
    final_review_markdown: str
