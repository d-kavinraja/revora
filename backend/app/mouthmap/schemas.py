"""MouthMap API schemas (stable Revora contract, decoupled from raw HF shape)."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class MouthMapConfig(BaseModel):
    model: str = "MouthMap"
    model_version: str
    input_frames: int = 75
    input_resolution: str = "46x140 grayscale"
    provider: str = "Hugging Face"
    compute: str = "Hosted Inference"
    max_upload_mb: int
    allowed_extensions: list[str]


class MouthMapHealth(BaseModel):
    status: Literal["available", "unavailable"]
    endpoint: str
    detail: str | None = None


class MouthMapWarm(BaseModel):
    status: Literal["ready"] = "ready"


class TestVideo(BaseModel):
    id: str
    filename: str
    duration_s: float | None = None
    resolution: str | None = None
    size_bytes: int | None = None
    ground_truth: str | None = None
    has_alignment: bool = False
    status: Literal["ready"] = "ready"


class InferenceResponse(BaseModel):
    prediction: str
    model: str = "MouthMap"
    model_version: str | None = None
    confidence: float | None = None
    inference_time_ms: int | None = None
    frames_processed: int | None = None
    status: Literal["completed"] = "completed"
    expected: str | None = None
    is_match: bool | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class HistoryItem(BaseModel):
    id: str
    video_filename: str
    source: str
    test_video_id: str | None = None
    prediction: str | None = None
    expected: str | None = None
    is_match: bool | None = None
    confidence: float | None = None
    inference_time_ms: int | None = None
    frames_processed: int | None = None
    model_version: str | None = None
    status: str
    created_at: str | None = None
