"""LangGraph-based multi-agent review pipeline.

Implements parallel execution of bug, security, and performance analysis
agents, with a coordinator that synthesizes the results.
"""

import uuid
import logging
from typing import Dict, Any

from langgraph.graph import StateGraph, END
from langgraph.types import Send

from app.ai.state import ReviewState
from app.ai.prompts import (
    BUG_FINDER_PROMPT,
    SECURITY_PROMPT,
    PERFORMANCE_PROMPT,
    COORDINATOR_PROMPT,
)
from app.ai.llm import llm_service

logger = logging.getLogger(__name__)


async def bug_agent(state: ReviewState) -> Dict[str, Any]:
    """Analyze code changes for bugs and logic errors."""
    try:
        prompt = BUG_FINDER_PROMPT.format(
            repo_context=str(state.get("repo_context", "")),
            diff_content=state.get("diff_content", ""),
        )
        result, _, _ = await llm_service.get_completion(
            user_id=uuid.UUID(state["user_id"]),
            provider=state.get("provider", "gemini"),
            messages=[{"role": "user", "content": prompt}],
            model=state.get("model"),
            api_key_id=state.get("api_key_id"),
        )
        return {"bug_analysis": [result or "Bug analysis unavailable"]}
    except Exception as e:
        logger.error(f"Bug agent failed: {e}")
        return {"bug_analysis": [f"Bug analysis unavailable: {str(e)}"]}


async def security_agent(state: ReviewState) -> Dict[str, Any]:
    """Analyze code changes for security vulnerabilities."""
    try:
        prompt = SECURITY_PROMPT.format(
            repo_context=str(state.get("repo_context", "")),
            diff_content=state.get("diff_content", ""),
        )
        result, _, _ = await llm_service.get_completion(
            user_id=uuid.UUID(state["user_id"]),
            provider=state.get("provider", "gemini"),
            messages=[{"role": "user", "content": prompt}],
            model=state.get("model"),
            api_key_id=state.get("api_key_id"),
        )
        return {"security_analysis": [result or "Security analysis unavailable"]}
    except Exception as e:
        logger.error(f"Security agent failed: {e}")
        return {"security_analysis": [f"Security analysis unavailable: {str(e)}"]}


async def performance_agent(state: ReviewState) -> Dict[str, Any]:
    """Analyze code changes for performance issues."""
    try:
        prompt = PERFORMANCE_PROMPT.format(
            repo_context=str(state.get("repo_context", "")),
            diff_content=state.get("diff_content", ""),
        )
        result, _, _ = await llm_service.get_completion(
            user_id=uuid.UUID(state["user_id"]),
            provider=state.get("provider", "gemini"),
            messages=[{"role": "user", "content": prompt}],
            model=state.get("model"),
            api_key_id=state.get("api_key_id"),
        )
        return {"performance_analysis": [result or "Performance analysis unavailable"]}
    except Exception as e:
        logger.error(f"Performance agent failed: {e}")
        return {"performance_analysis": [f"Performance analysis unavailable: {str(e)}"]}


async def coordinator_agent(state: ReviewState) -> Dict[str, Any]:
    """Synthesize results from all specialist agents into a final review."""
    try:
        bug_analysis = state.get("bug_analysis", [])
        security_analysis = state.get("security_analysis", [])
        performance_analysis = state.get("performance_analysis", [])

        prompt = COORDINATOR_PROMPT.format(
            pr_title=state.get("pr_title", ""),
            bug_analysis="\n".join(bug_analysis) if bug_analysis else "No bug analysis available",
            security_analysis="\n".join(security_analysis) if security_analysis else "No security analysis available",
            performance_analysis="\n".join(performance_analysis) if performance_analysis else "No performance analysis available",
        )
        result, _, _ = await llm_service.get_completion(
            user_id=uuid.UUID(state["user_id"]),
            provider=state.get("provider", "gemini"),
            messages=[{"role": "user", "content": prompt}],
            model=state.get("model"),
            api_key_id=state.get("api_key_id"),
        )
        return {"final_review_markdown": result or "Review generation failed"}
    except Exception as e:
        logger.error(f"Coordinator agent failed: {e}")
        return {"final_review_markdown": f"Review generation failed: {str(e)}"}


def _fan_out(state: ReviewState):
    """Fan out to all three specialist agents in parallel."""
    return [
        Send("bug_finder", state),
        Send("security_expert", state),
        Send("performance_expert", state),
    ]


def build_review_graph():
    """Build the multi-agent review graph with parallel execution.

    Graph structure:
        __start__ -> [bug_finder, security_expert, performance_expert] (parallel)
        bug_finder -> coordinator
        security_expert -> coordinator
        performance_expert -> coordinator
        coordinator -> __end__
    """
    workflow = StateGraph(ReviewState)

    # Add all four nodes
    workflow.add_node("bug_finder", bug_agent)
    workflow.add_node("security_expert", security_agent)
    workflow.add_node("performance_expert", performance_agent)
    workflow.add_node("coordinator", coordinator_agent)

    # Fan-out: start -> all 3 specialists in parallel
    workflow.add_conditional_edges("__start__", _fan_out)

    # Fan-in: all specialists -> coordinator
    workflow.add_edge("bug_finder", "coordinator")
    workflow.add_edge("security_expert", "coordinator")
    workflow.add_edge("performance_expert", "coordinator")

    # Coordinator -> end
    workflow.add_edge("coordinator", END)

    return workflow.compile()
