from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any


class EventType(str, Enum):
    STAGE_START = "stage.start"
    STAGE_PROGRESS = "stage.progress"
    STAGE_COMPLETE = "stage.complete"
    STAGE_FAILED = "stage.failed"
    STAGE_SKIPPED = "stage.skipped"
    AGENT_START = "agent.start"
    AGENT_COMPLETE = "agent.complete"
    LOG = "log"
    METRIC = "metric"
    CONTEXT_READY = "context.ready"
    TOKEN_USAGE = "token.usage"
    REVIEW_COMPLETE = "review.complete"
    ERROR = "error"


@dataclass
class PipelineEvent:
    type: EventType
    review_id: str
    stage: str
    status: str  # waiting, running, completed, failed, skipped
    message: str = ""
    timestamp: float = 0.0
    duration_ms: Optional[float] = None
    metrics: Optional[dict] = None
    progress: Optional[float] = None  # 0-100

    def to_sse(self) -> str:
        import json, time
        data = {
            "type": self.type.value,
            "review_id": self.review_id,
            "stage": self.stage,
            "status": self.status,
            "message": self.message,
            "timestamp": self.timestamp or time.time(),
        }
        if self.duration_ms is not None:
            data["duration_ms"] = self.duration_ms
        if self.metrics:
            data["metrics"] = self.metrics
        if self.progress is not None:
            data["progress"] = self.progress
        return json.dumps(data)


PIPELINE_STAGES = [
    ("queued", "Queued"),
    ("preparing_review", "Preparing Review"),
    ("cloning_repository", "Cloning Repository"),
    ("fetching_pull_request", "Fetching Pull Request"),
    ("analyzing_repository", "Analyzing Repository"),
    ("detecting_languages", "Detecting Languages"),
    ("detecting_frameworks", "Detecting Frameworks"),
    ("analyzing_architecture", "Analyzing Architecture"),
    ("building_dependency_graph", "Building Dependency Graph"),
    ("building_call_graph", "Building Call Graph"),
    ("building_import_graph", "Building Import Graph"),
    ("building_ast", "Building AST"),
    ("indexing_repository", "Indexing Repository"),
    ("retrieving_repository_knowledge", "Retrieving Repository Knowledge"),
    ("loading_repository_rules", "Loading Repository Rules"),
    ("running_static_analysis", "Running Static Analysis"),
    ("finding_related_files", "Finding Related Files"),
    ("ranking_context", "Ranking Context"),
    ("compressing_context", "Compressing Context"),
    ("building_prompt", "Building Prompt"),
    ("selecting_ai_provider", "Selecting AI Provider"),
    ("sending_request_to_llm", "Sending Request to LLM"),
    ("receiving_ai_response", "Receiving AI Response"),
    ("running_verification_agent", "Running Verification Agent"),
    ("removing_hallucinations", "Removing Hallucinations"),
    ("deduplicating_findings", "Deduplicating Findings"),
    ("ranking_severity", "Ranking Severity"),
    ("generating_review_summary", "Generating Review Summary"),
    ("formatting_github_review", "Formatting GitHub Review"),
    ("publishing_review", "Publishing Review"),
    ("completed", "Completed"),
]
