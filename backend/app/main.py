import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.ai.model_registry import canonical_registry
from app.api.v1.router import api_router
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.services.recovery import recover_stale_reviews_on_startup
from app.services.sync_engine import SYNC_REASON_STARTUP, run_sync_pass, sync_loop
from app.queue.worker import run_worker

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup recovery, full sync, background sync, shutdown."""
    canonical_registry.discover_models()

    # Fail reviews stuck in active statuses with no backing job so the
    # per-PR active-review lock is always released after a restart.
    try:
        await recover_stale_reviews_on_startup()
    except Exception:
        logger.exception("Startup recovery failed")

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
    except Exception as e:  # noqa: BLE001
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
