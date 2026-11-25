'''Speech-to-text API schemas. No audio, transcript or service URL appears
in any admin response.'''

from pydantic import BaseModel, Field


class SpeechConfigResponse(BaseModel):
    enabled: bool
    max_recording_seconds: int
    max_audio_mb: int


class SpeechEngineInfo(BaseModel):
    model: str = 'tiny.en'
    device: str = 'cpu'
    compute_type: str = 'int8'
    language: str = 'en'
    max_concurrent_inferences: int = 1


class SpeechServiceInfo(BaseModel):
    configured: bool = False
    reachable: bool = False
    ready: bool = False
    state: str = 'unavailable'
    active: int = 0
    queued: int = 0
    capacity: int = 4
    error: str | None = None


class SpeechReadinessResponse(BaseModel):
    enabled: bool
    state: str
    ready: bool
    max_recording_seconds: int = 60
    max_audio_mb: int = 5


class AdminSpeechStatus(BaseModel):
    enabled: bool
    environment_enabled: bool
    version: int
    max_recording_seconds: int
    max_audio_mb: int
    queue_timeout_s: int
    engine: SpeechEngineInfo
    service: SpeechServiceInfo


class AdminSpeechUpdate(BaseModel):
    enabled: bool
    max_recording_seconds: int = Field(default=60, ge=5, le=60)
    max_audio_mb: int = Field(default=5, ge=1, le=5)
    queue_timeout_s: int = Field(default=30, ge=5, le=60)
    version: int = Field(default=0, ge=0)
