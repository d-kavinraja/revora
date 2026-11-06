import uuid
from datetime import datetime

from pydantic import BaseModel


class OperationJobRead(BaseModel):
    id: uuid.UUID
    operation_type: str
    status: str
    payload: dict | None = None
    result: dict | None = None
    progress_current: int = 0
    progress_total: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_text: str | None = None

    model_config = {"from_attributes": True}
