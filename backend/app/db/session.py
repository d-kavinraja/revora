import socket
import logging
import datetime
import asyncio
from urllib.parse import urlparse
from typing import AsyncGenerator
from sqlalchemy import event
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine, AsyncEngine
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB as PG_JSONB

from app.core.config import settings
from app.db.base import Base
import app.models  # Register all models on Base.metadata

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

async def get_engine_and_sessionmaker():
    global _engine, _sessionmaker
    if _engine is not None:
        return _engine, _sessionmaker

    async with _init_lock:
        if _engine is not None:
            return _engine, _sessionmaker

        db_url = getattr(settings, "DATABASE_URL", None)
        is_sqlite = False

        if not db_url:
            is_sqlite = True
            db_url = "sqlite+aiosqlite:///revora.db"
            logger.warning("DATABASE_URL is missing. Falling back to local SQLite database.")
        else:
            # Check connectable in executor to prevent blocking
            loop = asyncio.get_running_loop()
            connectable = await loop.run_in_executor(None, is_db_connectable, db_url)
            if not connectable:
                is_sqlite = True
                db_url = "sqlite+aiosqlite:///revora.db"
                logger.warning(f"Database at {settings.DATABASE_URL} is unreachable. Falling back to local SQLite database.")

        if is_sqlite:
            engine = create_async_engine(
                db_url,
                echo=settings.APP_ENV == "development",
                future=True,
                connect_args={"check_same_thread": False, "timeout": 30.0},
            )

            # Register SQLite specific functions and WAL/busy_timeout settings
            @event.listens_for(engine.sync_engine, "connect")
            def configure_sqlite_connection(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.close()
                dbapi_connection.create_function("now", 0, lambda: datetime.datetime.utcnow().isoformat())
            
            # Automatically perform Base.metadata.create_all for SQLite fallback
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Successfully created/verified SQLite database schema.")
        else:
            engine = create_async_engine(
                db_url,
                echo=settings.APP_ENV == "development",
                future=True,
                pool_pre_ping=True,
            )

        sessionmaker_local = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

        _engine = engine
        _sessionmaker = sessionmaker_local
        return _engine, _sessionmaker

class LazyAsyncSession:
    """
    Transparent session wrapper that performs lazy engine initialization 
    when the context manager is entered or when attributes are accessed.
    """
    def __init__(self):
        self._session = None

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            _, sessionmaker_local = await get_engine_and_sessionmaker()
            self._session = sessionmaker_local()
        return self._session

    async def __aenter__(self):
        session = await self._get_session()
        await session.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session is not None:
            await self._session.__aexit__(exc_type, exc_val, exc_tb)

    def __getattr__(self, name):
        if self._session is None:
            raise RuntimeError(f"Session not initialized. Cannot access attribute '{name}' before initialization.")
        return getattr(self._session, name)

def AsyncSessionLocal() -> LazyAsyncSession:
    return LazyAsyncSession()

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides an async database session per request.
    Closes the session when the request completes.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
