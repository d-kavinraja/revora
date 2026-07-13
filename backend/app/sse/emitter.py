import time
import json
import logging
import asyncio
from typing import AsyncGenerator, Optional, Callable, Awaitable

from app.sse.events import EventType, PipelineEvent

logger = logging.getLogger(__name__)


class SSEEmitter:
    """Emits SSE events for real-time pipeline visualization."""

    def __init__(self, review_id: str):
        self.review_id = review_id
        self._queue: asyncio.Queue = asyncio.Queue()
        self._stage_timers: dict[str, float] = {}
        self._events: list[dict] = []

    async def emit(
        self,
        stage: str,
        status: str,
        event_type: EventType = EventType.STAGE_START,
        message: str = "",
        metrics: Optional[dict] = None,
        progress: Optional[float] = None,
    ) -> None:
        now = time.time()
        duration_ms = None

        if status == "running":
            self._stage_timers[stage] = now
        elif status in ("completed", "failed") and stage in self._stage_timers:
            duration_ms = (now - self._stage_timers[stage]) * 1000
            del self._stage_timers[stage]

        event = PipelineEvent(
            type=event_type,
            review_id=self.review_id,
            stage=stage,
            status=status,
            message=message,
            timestamp=now,
            duration_ms=duration_ms,
            metrics=metrics,
            progress=progress,
        )

        self._events.append({
            "type": event.type.value,
            "stage": event.stage,
            "status": event.status,
            "message": event.message,
            "timestamp": event.timestamp,
            "duration_ms": event.duration_ms,
            "metrics": event.metrics,
        })

        await self._queue.put(event)

    async def emit_log(self, stage: str, message: str) -> None:
        await self.emit(stage, "running", EventType.LOG, message)

    async def emit_metric(self, stage: str, metrics: dict) -> None:
        await self.emit(stage, "running", EventType.METRIC, message=json.dumps(metrics), metrics=metrics)

    async def emit_error(self, stage: str, error: str) -> None:
        await self.emit(stage, "failed", EventType.STAGE_FAILED, message=error)

    async def stream(self) -> AsyncGenerator[str, None]:
        for event_data in self._events:
            yield f"data: {json.dumps(event_data)}\n\n"

        while True:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=30)
                yield f"data: {event.to_sse()}\n\n"
                if event.stage == "completed" and event.status == "completed":
                    break
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': time.time()})}\n\n"

    def get_events(self) -> list[dict]:
        return self._events
