from typing import TypedDict, List, Dict, Any, Optional

class ReviewState(TypedDict):
    """LangGraph State for the PR Review Pipeline"""
    pr_number: int
    pr_title: str
    pr_description: str
    diff_content: str
    repo_context: Dict[str, Any]
    
    # User / Auth Context
    user_id: str
    provider: str
    model: Optional[str]
    api_key_id: Optional[str]
    
    # Agent Outputs
    bug_analysis: List[str]
    security_analysis: List[str]
    performance_analysis: List[str]
    style_analysis: List[str]
    
    # Final Output
    final_review_markdown: str
