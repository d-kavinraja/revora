from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import settings
from app.api.v1.router import api_router
from app.ai.model_registry import canonical_registry
from app.db.session import AsyncSessionLocal


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown hooks."""
    canonical_registry.discover_models()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    description="API for the Revora AI-powered Pull Request Review Platform",
    version="1.0.0",
    lifespan=lifespan,
)

from app.middleware.correlation import CorrelationIdMiddleware
from app.middleware.rate_limit import limiter
from app.middleware.size_limit import RequestSizeLimitMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

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
            content={"status": "not_ready", "database": "disconnected", "error": str(e)},
        )


@app.get("/")
async def root():
    return {"message": "Welcome to Revora API. Visit /docs for the API documentation."}
