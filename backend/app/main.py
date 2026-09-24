import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text

from app.ai.model_registry import canonical_registry
from app.api.v1.router import api_router
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.sync_run import SYNC_STATUS_QUEUED, SYNC_STATUS_RUNNING, SyncRun
from app.queue.worker import run_worker
from app.services.recovery import recover_stale_reviews_on_startup
from app.services.sync_engine import (
    SYNC_REASON_STARTUP,
    record_sync_run,
    run_sync_pass,
    sync_loop,
)

logger = logging.getLogger(__name__)


async def _process_queued_sync_on_startup(run_id: uuid.UUID, repo_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
    """Process a QUEUED sync run on startup (simplified version without full retry loop)."""
    from app.api.v1.endpoints.repositories import _background_single_repo_sync_with_retry

    async with AsyncSessionLocal() as db:
        run = await db.execute(select(SyncRun).where(SyncRun.id == run_id))
        run = run.scalars().first()
        if not run or run.status != SYNC_STATUS_QUEUED:
            return

        await record_sync_run(db, run.reason, SYNC_STATUS_RUNNING, run_id=run_id)

    await _background_single_repo_sync_with_retry(repo_id, run_id, user_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup recovery, full sync, background sync, shutdown."""
    import sys

    is_testing = "pytest" in sys.modules

    canonical_registry.discover_models()

    if is_testing:
        yield
        return

    # Fail reviews stuck in active statuses with no backing job so the
    # per-PR active-review lock is always released after a restart.
    try:
        await recover_stale_reviews_on_startup()
    except Exception:
        logger.exception("Startup recovery failed")

    # Recover orphaned QUEUED sync runs (from webhook initial syncs, login, etc.)
    # that were created before a restart but never picked up.
    try:
        async with AsyncSessionLocal() as db:
            queued_runs = await db.execute(
                select(SyncRun).where(
                    SyncRun.status == SYNC_STATUS_QUEUED,
                    SyncRun.started_at < datetime.now(UTC) - timedelta(minutes=5),
                )
            )
            for run in queued_runs.scalars().all():
                # Re-schedule via background processor
                repo_id = uuid.UUID(run.details["repo_id"])
                user_id = run.triggered_by
                asyncio.create_task(_process_queued_sync_on_startup(run.id, repo_id, user_id))
    except Exception:
        logger.exception("QUEUED sync recovery failed")

    # Automatic recovery after downtime: one full sync pass — discovers new /
    # removed repositories, new / reopened / closed / merged PRs, new commits,
    # and enqueues the reviews that were missed while the server was down.
    async def startup_sync():
        try:
            result = await run_sync_pass(SYNC_REASON_STARTUP)
            logger.info(f"Startup sync pass complete: {result.get('status')}")
        except Exception:
            logger.exception("Startup sync pass failed")

    startup_sync_task = asyncio.create_task(startup_sync())

    # Background tiered sync (missed webhooks / dropped SSE connections).
    sync_task = None
    if settings.SYNC_RECOVERY_INTERVAL_MINUTES > 0:
        sync_task = asyncio.create_task(sync_loop())

    worker_task = asyncio.create_task(run_worker(standalone=False))

    try:
        yield
    finally:
        worker_task.cancel()
        if sync_task:
            sync_task.cancel()
        if startup_sync_task and not startup_sync_task.done():
            startup_sync_task.cancel()
            try:
                if sync_task:
                    await sync_task
                await startup_sync_task
                await worker_task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title=settings.APP_NAME,
    description="API for the Revora AI-powered Pull Request Review Platform",
    version="1.0.0",
    lifespan=lifespan,
)

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.middleware.correlation import CorrelationIdMiddleware
from app.middleware.rate_limit import limiter
from app.middleware.size_limit import RequestSizeLimitMiddleware

# Configure Middleware
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(RequestSizeLimitMiddleware, max_upload_size=10 * 1024 * 1024)
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health_check():
    """Static health check — always returns healthy if the process is up."""
    return {"status": "healthy", "service": "revora-api"}


@app.get("/livez")
async def liveness():
    """Liveness probe — confirms the process is running."""
    return {"status": "ok"}


@app.get("/readyz")
async def readiness():
    """Readiness probe — verifies DB connectivity.

    Used by orchestrators (k8s, Docker healthchecks) to determine
    whether the instance can accept traffic. Returns 503 if the
    database is unreachable.
    """
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        return {"status": "ready", "database": "connected"}
    except Exception as e:
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "database": "disconnected",
                "error": str(e),
            },
        )


@app.get("/")
async def root():
    return {"message": "Welcome to Revora API. Visit /docs for the API documentation."}
