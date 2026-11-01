"""BotaniQ API schemas (stable Revora contract, decoupled from raw HF shape)."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class Top5Prediction(BaseModel):
    rank: int
    label: str
    confidence: float


class BotaniQConfig(BaseModel):
    model: str = "BotaniQ"
    model_version: str
    input_resolution: str = "224x224 RGB"
    provider: str = "Hugging Face"
    compute: str = "Hosted Inference"
    max_upload_mb: int
    allowed_extensions: list[str]
    classes_available: int | None = None


class BotaniQHealth(BaseModel):
    status: Literal["available", "unavailable"]
    endpoint: str
    detail: str | None = None


class BotaniQWarm(BaseModel):
    status: Literal["ready"] = "ready"


class SampleImage(BaseModel):
    id: str
    filename: str
    size_bytes: int | None = None
    label: str | None = None          # ground-truth class label if known
    plant_name: str | None = None
    plant_type: str | None = None
    status: Literal["ready"] = "ready"


class InferenceResponse(BaseModel):
    prediction: str                              # display name e.g. "Tulsi Leaf"
    predicted_class: str | None = None           # raw key e.g. "leaf_Tulsi"
    plant_name: str | None = None
    plant_type: str | None = None
    confidence: float | None = None              # 0–100
    model: str = "BotaniQ"
    model_version: str | None = None
    classes_available: int | None = None
    top_5_predictions: list[Top5Prediction] = Field(default_factory=list)
    inference_time_ms: int | None = None
    status: Literal["completed"] = "completed"
    raw: dict[str, Any] = Field(default_factory=dict)


class HistoryItem(BaseModel):
    id: str
    image_filename: str
    source: str
    test_image_id: str | None = None
    prediction: str | None = None
    predicted_class: str | None = None
    plant_name: str | None = None
    plant_type: str | None = None
    confidence: float | None = None
    top_5_predictions: list[Top5Prediction] = Field(default_factory=list)
    inference_time_ms: int | None = None
    model_version: str | None = None
    status: str
    created_at: str | None = None
