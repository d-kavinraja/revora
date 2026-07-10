import uuid
import asyncio
from typing import Dict, Any

from app.worker.celery_app import celery_app
from app.ai.graph import build_review_graph
from app.ai.state import ReviewState

# Synchronous wrapper for async graph execution
def run_async_graph(state: ReviewState) -> Dict[str, Any]:
    graph = build_review_graph()
    result = asyncio.run(graph.ainvoke(state))
    return result

@celery_app.task(name="process_pull_request_review")
def process_pull_request_review(pr_data: Dict[str, Any]):
    """
    Background task to process a PR review.
    1. Clone repository
    2. Extract diff & context
    3. Run AI graph
    4. Post results back to GitHub
    """
    print(f"Starting review process for PR: {pr_data.get('pr_number')}")
    
    # Example state initialization
    initial_state = ReviewState(
        pr_number=pr_data.get("pr_number", 0),
        pr_title=pr_data.get("title", ""),
        pr_description=pr_data.get("description", ""),
        diff_content=pr_data.get("diff", ""),
        repo_context={}, # Would be populated by RCE
        user_id=pr_data.get("user_id"),
        provider=pr_data.get("provider", "openai"),
        model=None,
        bug_analysis=[],
        security_analysis=[],
        performance_analysis=[],
        style_analysis=[],
        final_review_markdown=""
    )
    
    # Execute graph
    final_state = run_async_graph(initial_state)
    
    # Save results / post to github
    print(f"Finished review. Output length: {len(final_state.get('final_review_markdown', ''))}")
    return {"status": "success", "review_length": len(final_state.get('final_review_markdown', ''))}
