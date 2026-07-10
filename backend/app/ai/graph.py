import uuid
from typing import Dict, Any

from langgraph.graph import StateGraph, END

from app.ai.state import ReviewState
from app.ai.prompts import BUG_FINDER_PROMPT, SECURITY_PROMPT, PERFORMANCE_PROMPT, COORDINATOR_PROMPT
from app.ai.llm import llm_service

async def bug_agent(state: ReviewState):
    prompt = BUG_FINDER_PROMPT.format(
        repo_context=str(state["repo_context"]),
        diff_content=state["diff_content"]
    )
    result = await llm_service.get_completion(
        user_id=uuid.UUID(state["user_id"]),
        provider=state["provider"],
        messages=[{"role": "user", "content": prompt}],
        model=state.get("model")
    )
    state["bug_analysis"] = [result]
    return state

async def security_agent(state: ReviewState):
    prompt = SECURITY_PROMPT.format(
        repo_context=str(state["repo_context"]),
        diff_content=state["diff_content"]
    )
    result = await llm_service.get_completion(
        user_id=uuid.UUID(state["user_id"]),
        provider=state["provider"],
        messages=[{"role": "user", "content": prompt}],
        model=state.get("model")
    )
    state["security_analysis"] = [result]
    return state

async def performance_agent(state: ReviewState):
    prompt = PERFORMANCE_PROMPT.format(
        repo_context=str(state["repo_context"]),
        diff_content=state["diff_content"]
    )
    result = await llm_service.get_completion(
        user_id=uuid.UUID(state["user_id"]),
        provider=state["provider"],
        messages=[{"role": "user", "content": prompt}],
        model=state.get("model")
    )
    state["performance_analysis"] = [result]
    return state

async def coordinator_agent(state: ReviewState):
    prompt = COORDINATOR_PROMPT.format(
        pr_title=state["pr_title"],
        bug_analysis="\n".join(state["bug_analysis"]),
        security_analysis="\n".join(state["security_analysis"]),
        performance_analysis="\n".join(state["performance_analysis"])
    )
    result = await llm_service.get_completion(
        user_id=uuid.UUID(state["user_id"]),
        provider=state["provider"],
        messages=[{"role": "user", "content": prompt}],
        model=state.get("model")
    )
    state["final_review_markdown"] = result
    return state

def build_review_graph():
    workflow = StateGraph(ReviewState)
    
    # Add nodes
    workflow.add_node("bug_finder", bug_agent)
    workflow.add_node("security_expert", security_agent)
    workflow.add_node("performance_expert", performance_agent)
    workflow.add_node("coordinator", coordinator_agent)
    
    # Parallel execution of specialists
    workflow.set_entry_point("bug_finder")
    # In a real setup, we would route from entry to all 3 in parallel
    # LangGraph handles parallel branches by default if we add edges from start to multiple
    workflow.add_edge("bug_finder", "coordinator")
    workflow.add_edge("security_expert", "coordinator")
    workflow.add_edge("performance_expert", "coordinator")
    
    workflow.add_edge("coordinator", END)
    
    return workflow.compile()
