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
from app.services.admin_audit import admin_audit
from app.services.admin_auth import get_admin_by_username, provision_admin
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
    from app.api.v1.endpoints.repositories import (
        _background_single_repo_sync_with_retry,
    )

    async with AsyncSessionLocal() as db:
        run = await db.execute(select(SyncRun).where(SyncRun.id == run_id))
        run = run.scalars().first()
        if not run or run.status != SYNC_STATUS_QUEUED:
            return

        await record_sync_run(db, run.reason, SYNC_STATUS_RUNNING, run_id=run_id)

    await _background_single_repo_sync_with_retry(repo_id, run_id, user_id)


async def _bootstrap_admin_from_env() -> None:
    """Optional deploy-time admin provisioning (never overwrites).

    Runs only when ADMIN_BOOTSTRAP_USERNAME is set. Creates the admin from
    ADMIN_BOOTSTRAP_PASSWORD(_HASH) when no such username exists; existing
    admins are never overwritten or rotated implicitly.
    """
    username = settings.ADMIN_BOOTSTRAP_USERNAME
    if not username:
        return
    password = settings.ADMIN_BOOTSTRAP_PASSWORD
    password_hash = settings.ADMIN_BOOTSTRAP_PASSWORD_HASH
    if not password and not password_hash:
        logger.warning(
            "ADMIN_BOOTSTRAP_USERNAME is set but no password/hash is configured; skipping."
        )
        return

    async with AsyncSessionLocal() as db:
        existing = await get_admin_by_username(db, username)
        if existing is not None:
            return
        admin = await provision_admin(
            db,
            username=username,
            password=password,
            password_hash=password_hash,
        )
        await admin_audit(
            db,
            action="admin.bootstrap",
            entity_type="admin_user",
            entity_id=str(admin.id),
            details={"source": "env"},
        )
        logger.info("Bootstrap admin created from environment (username=%s)", admin.username)


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

    # Optional env-driven admin provisioning (no-op when unset).
    try:
        await _bootstrap_admin_from_env()
    except Exception:
        logger.exception("Admin bootstrap failed")

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

from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.deps_flags import FeatureDisabledError
from app.middleware.correlation import CorrelationIdMiddleware
from app.middleware.maintenance import MaintenanceMiddleware
from app.middleware.rate_limit import SlowAPIMiddleware, limiter
from app.middleware.size_limit import OriginCheckMiddleware, RequestSizeLimitMiddleware

# Configure Middleware
app.state.limiter = limiter
# Origin allow-list consumed by OriginCheckMiddleware (CSRF layer 2).
# Values are netlocs (host[:port]) so both full origins and scheme-less
# entries are comparable against the Origin header.
from urllib.parse import urlparse as _urlparse


def _netloc_or_raw(u: str) -> str:
    p = _urlparse(u)
    return p.netloc or p.path


app.state.cors_origins = [_netloc_or_raw(o) for o in settings.CORS_ORIGINS]
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


async def _feature_disabled_handler(request, exc: FeatureDisabledError) -> JSONResponse:
    """Exact §11.1 payload: `503 {"code": "feature_disabled", "message": ...}`."""
    return JSONResponse(
        status_code=503,
        content={"code": "feature_disabled", "message": exc.message},
    )


app.add_exception_handler(FeatureDisabledError, _feature_disabled_handler)
# Maintenance gate: added FIRST so Starlette LIFO makes it the innermost
# middleware — it executes after CORS/Correlation/SizeLimit/OriginCheck/
# SlowAPI and immediately before route dispatch (§12.3 placement note).
app.add_middleware(MaintenanceMiddleware)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(OriginCheckMiddleware)
app.add_middleware(RequestSizeLimitMiddleware, max_upload_size=10 * 1024 * 1024)
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Hub-Signature-256",
        "X-GitHub-Delivery",
        "X-GitHub-Event",
        "X-Request-ID",
        "X-Correlation-ID",
        "ngrok-skip-browser-warning",
    ],
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
    except Exception:
        from fastapi.responses import JSONResponse

        # Generic message: never reflect driver/host details to callers.
        logger.warning("Readiness probe: database unreachable", exc_info=True)
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "database": "disconnected",
            },
        )


@app.get("/")
async def root():
    return {"message": "Welcome to Revora API. Visit /docs for the API documentation."}
