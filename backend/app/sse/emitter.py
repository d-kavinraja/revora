import time
import json
import logging
import asyncio
from typing import AsyncGenerator, Optional, Callable, Awaitable

from app.sse.events import EventType, PipelineEvent

logger = logging.getLogger(__name__)


class SSEEmitter:
    """Emits SSE events for real-time pipeline visualization using Redis Pub/Sub."""

    def __init__(self, review_id: str):
        self.review_id = review_id
        self._queue: asyncio.Queue = asyncio.Queue()
        self._stage_timers: dict[str, float] = {}
        self._events: list[dict] = []
        self._channel = f"sse:review:{review_id}"
        self._redis = None
        
        from app.core.config import settings
        if settings.REDIS_URL:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

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

        event_sse = event.to_sse()
        
        # Local fallback tracking
        self._events.append(json.loads(event_sse))
        await self._queue.put(event)

        if self._redis:
            try:
                # Publish to all connected replicas
                await self._redis.publish(self._channel, event_sse)
                # Save to history for re-connection
                await self._redis.rpush(f"events:{self.review_id}", event_sse)
                await self._redis.expire(f"events:{self.review_id}", 3600)
            except Exception as e:
                logger.error(f"Redis publish error: {e}")

    async def emit_log(self, stage: str, message: str) -> None:
        await self.emit(stage, "running", EventType.LOG, message)

    async def emit_metric(self, stage: str, metrics: dict) -> None:
        await self.emit(stage, "running", EventType.METRIC, message=json.dumps(metrics), metrics=metrics)

    async def emit_error(self, stage: str, error: str) -> None:
        await self.emit(stage, "failed", EventType.STAGE_FAILED, message=error)

    async def stream(self) -> AsyncGenerator[str, None]:
        if self._redis:
            # Yield historical events first
            try:
                historical = await self._redis.lrange(f"events:{self.review_id}", 0, -1)
                for evt_str in historical:
                    yield f"data: {evt_str}\n\n"
                    
                pubsub = self._redis.pubsub()
                await pubsub.subscribe(self._channel)
                
                while True:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15.0)
                    if message:
                        data = message['data']
                        yield f"data: {data}\n\n"
                        # Check termination conditions
                        if '"status": "completed"' in data and '"stage": "completed"' in data:
                            break
                        if '"status": "failed"' in data:
                            break
                    else:
                        yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': time.time()})}\n\n"
                
                await pubsub.unsubscribe(self._channel)
                await pubsub.close()
                return
            except Exception as e:
                logger.error(f"Redis SSE stream error: {e}")
                # Fall through to local queue logic if Redis fails

        # Local Queue Fallback (Single-Node Dev Mode)
        for event_data in self._events:
            yield f"data: {json.dumps(event_data)}\n\n"

        while True:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=30)
                yield f"data: {event.to_sse()}\n\n"
                if event.stage == "completed" and event.status == "completed":
                    break
                if event.status == "failed":
                    break
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': time.time()})}\n\n"

    def get_events(self) -> list[dict]:
        return self._events
