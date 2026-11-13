import asyncio
import datetime
import logging
import socket
from collections.abc import AsyncGenerator
from urllib.parse import urlparse

from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles

from app.core.config import settings
from app.db.base import Base

logger = logging.getLogger(__name__)


def is_db_connectable(url: str) -> bool:
    try:
        if url.startswith("sqlite"):
            return True
        cleaned = url.split("://")[-1]
        parsed = urlparse("http://" + cleaned)
        host = parsed.hostname or "localhost"
        port = parsed.port or 5432
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except Exception:
        return False


# Register SQLite compilers for PostgreSQL-specific types
@compiles(PG_UUID, "sqlite")
def compile_uuid_sqlite(type_, compiler, **kw):
    return "CHAR(32)"


@compiles(PG_JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "TEXT"


_engine: AsyncEngine | None = None
_sessionmaker = None
_init_lock = asyncio.Lock()


def _sanitize_db_error(exc: BaseException) -> str:
    """Return a sanitized, bounded description of a DB error.

    Never include connection URLs, credentials, or query parameters.
    """
    import re

    text = f"{type(exc).__name__}: {exc}"
    # Redact anything that looks like a connection string or secret.
    text = re.sub(r"[A-Za-z]+://[^\s'\"]+", "[redacted-url]", text)
    text = re.sub(r"password\s*=\s*\S+", "password=[redacted]", text, flags=re.IGNORECASE)
    return text[:500]


async def get_engine_and_sessionmaker():
    global _engine, _sessionmaker
    if _engine is not None:
        return _engine, _sessionmaker

    async with _init_lock:
        if _engine is not None:
            return _engine, _sessionmaker

        db_url = getattr(settings, "DATABASE_URL", None)
        is_sqlite = False
        is_production = getattr(settings, "APP_ENV", "development") not in (
            "development",
            "testing",
        )

        if not db_url:
            if is_production:
                raise RuntimeError(
                    "DATABASE_URL is required in production; refusing SQLite fallback."
                )
            is_sqlite = True
            db_url = "sqlite+aiosqlite:///revora.db"
            logger.warning(
                "DATABASE_URL is missing. Falling back to local SQLite database."
            )
        else:
            loop = asyncio.get_running_loop()
            connectable = await loop.run_in_executor(None, is_db_connectable, db_url)
            if not connectable:
                if is_production:
                    raise RuntimeError(
                        "Configured database is unreachable in production; "
                        "refusing SQLite fallback."
                    )
                is_sqlite = True
                db_url = "sqlite+aiosqlite:///revora.db"
                logger.warning(
                    "Configured database is unreachable. Falling back to local SQLite database."
                )

        if is_sqlite:
            engine = create_async_engine(
                db_url,
                echo=settings.APP_ENV == "development",
                future=True,
                connect_args={"check_same_thread": False, "timeout": 30.0},
            )

            @event.listens_for(engine.sync_engine, "connect")
            def configure_sqlite_connection(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.close()
                dbapi_connection.create_function(
                    "now", 0, lambda: datetime.datetime.now(datetime.UTC).isoformat()
                )

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Successfully created/verified SQLite database schema.")
        else:
            engine_kwargs = {
                "echo": settings.APP_ENV == "development",
                "future": True,
                "pool_pre_ping": True,
            }
            # Apply pool settings only when explicitly configured.
            pool_size = getattr(settings, "DATABASE_POOL_SIZE", None)
            max_overflow = getattr(settings, "DATABASE_MAX_OVERFLOW", None)
            pool_timeout = getattr(settings, "DATABASE_POOL_TIMEOUT", None)
            pool_recycle = getattr(settings, "DATABASE_POOL_RECYCLE", None)
            if pool_size is not None:
                engine_kwargs["pool_size"] = pool_size
            if max_overflow is not None:
                engine_kwargs["max_overflow"] = max_overflow
            if pool_timeout is not None:
                engine_kwargs["pool_timeout"] = pool_timeout
            if pool_recycle is not None:
                engine_kwargs["pool_recycle"] = pool_recycle

            engine = create_async_engine(db_url, **engine_kwargs)

            # Log topology without exposing credentials.
            try:
                parsed = urlparse(db_url.split("://", 1)[-1])
                host = (parsed.hostname or "").lower()
                if "pooler" in host or "pgbouncer" in host:
                    topology = "pooled"
                elif host:
                    topology = "direct"
                else:
                    topology = "unknown"
                logger.info("Database topology: %s", topology)
            except Exception:
                logger.info("Database topology: unknown")

        sessionmaker_local = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

        _engine = engine
        _sessionmaker = sessionmaker_local
        return _engine, _sessionmaker


class DatabaseSession:
    """Lazy, single-owner async database session context manager.

    ``__aenter__`` returns a real ``AsyncSession``. ``__aexit__`` performs the
    single cleanup (commit/rollback/close as decided by SQLAlchemy). Cleanup
    errors are logged and never mask an in-flight application exception.
    """

    def __init__(self):
        self._session: AsyncSession | None = None

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            _, sessionmaker_local = await get_engine_and_sessionmaker()
            self._session = sessionmaker_local()
        return self._session

    async def __aenter__(self) -> AsyncSession:
        session = await self._get_session()
        await session.__aenter__()
        return session

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session is None:
            return False
        session = self._session
        self._session = None
        try:
            await session.__aexit__(exc_type, exc_val, exc_tb)
        except Exception as cleanup_exc:
            logger.warning(
                "Database session cleanup failed: %s",
                _sanitize_db_error(cleanup_exc),
                exc_info=True,
            )
        return False


def AsyncSessionLocal() -> DatabaseSession:
    return DatabaseSession()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that provides one AsyncSession per request.

    Cleanup is owned exclusively by ``DatabaseSession`` (via ``async with``).
    """
    async with AsyncSessionLocal() as session:
        yield session


async def dispose_engine() -> None:
    """Dispose the global engine (idempotent)."""
    global _engine, _sessionmaker
    async with _init_lock:
        if _engine is not None:
            try:
                await _engine.dispose()
            except Exception as exc:
                logger.warning(
                    "Engine disposal failed: %s", _sanitize_db_error(exc), exc_info=True
                )
            finally:
                _engine = None
                _sessionmaker = None
