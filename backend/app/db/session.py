import asyncio
import datetime
import logging
import re
import socket
from collections.abc import AsyncGenerator
from urllib.parse import urlparse

import sqlalchemy
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles

from app.core import config as config_module
from app.db.base import Base

logger = logging.getLogger(__name__)

try:
    import asyncpg

    _ASYNCPG_ERRORS = (
        asyncpg.exceptions.InterfaceError,
        asyncpg.exceptions.PostgresConnectionError,
        asyncpg.exceptions.ConnectionDoesNotExistError,
    )
except Exception:
    _ASYNCPG_ERRORS = ()

_INSTRUMENTED_ENGINES: set[int] = set()

_SQLSTATE_CATEGORIES = {
    "08000": "connection_lost",
    "08001": "connection_lost",
    "08003": "connection_lost",
    "08004": "connection_lost",
    "08006": "connection_lost",
    "08007": "connection_lost",
    "25P03": "idle_in_transaction_timeout",
    "53300": "too_many_connections",
    "57P01": "server_shutdown",
    "57P02": "server_shutdown",
    "57P03": "cannot_connect_now",
    "57P05": "idle_session_timeout",
}

_CLOSED_CONNECTION_MESSAGES = (
    "underlying connection is closed",
    "connection is closed",
    "connection was closed",
)


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


@compiles(PG_UUID, "sqlite")
def compile_uuid_sqlite(type_, compiler, **kw):
    return "CHAR(32)"


@compiles(PG_JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "TEXT"


def _sanitize_db_error(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    text = re.sub(r"[A-Za-z]+://[^\s'\"]+", "[redacted-url]", text)
    text = re.sub(r"(?i)password\s*=\s*\S+", "password=[redacted]", text)
    text = re.sub(r"(?i)\b(host|user|dbname|database)\s*=\s*\S+", r"\1=[redacted]", text)
    text = re.sub(r"\[SQL:.*", "[sql-redacted]", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"\[parameters:.*", "[parameters-redacted]", text, flags=re.IGNORECASE | re.DOTALL)
    text = "".join(ch if ch.isprintable() or ch in "\r\n\t" else "?" for ch in text)
    return text[:500]


def _iter_exception_chain(exc: BaseException | None):
    seen: set[int] = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        cause = getattr(current, "__cause__", None)
        context = getattr(current, "__context__", None)
        current = cause if cause is not None else context


def _sqlstate(exc: BaseException | None) -> str | None:
    for item in _iter_exception_chain(exc):
        for attr in ("sqlstate", "pgcode", "sqlstate_code"):
            value = getattr(item, attr, None)
            if value:
                return str(value)
        orig = getattr(item, "orig", None)
        if orig is not None and orig is not item:
            for attr in ("sqlstate", "pgcode", "sqlstate_code"):
                value = getattr(orig, attr, None)
                if value:
                    return str(value)
    return None


def _get_correlation_id() -> str | None:
    try:
        from app.middleware.correlation import get_correlation_id

        value = get_correlation_id()
    except Exception:
        return None
    if value is None:
        return None
    value = re.sub(r"[^A-Za-z0-9_.:-]", "", str(value))[:128]
    return value or None


def _safe_log_value(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return re.sub(r"[\x00-\x1f\x7f]", " ", value)[:200]
    return str(value)[:200]


def _call_if_callable(value):
    if callable(value):
        try:
            return value()
        except Exception:
            return None
    return value


def _backend_pid(dbapi_connection) -> int | None:
    if dbapi_connection is None:
        return None
    candidates = [dbapi_connection]
    for attr in ("driver_connection", "connection", "_connection", "raw_connection", "dbapi_connection"):
        obj = getattr(dbapi_connection, attr, None)
        if obj is not None:
            candidates.append(obj)
    for obj in candidates:
        getter = getattr(obj, "get_server_pid", None)
        if callable(getter):
            try:
                value = getter()
                if value is not None:
                    return int(value)
            except Exception as exc:
                logger.debug("Could not read backend pid: %s", exc)
                continue
    return None


def _classify_db_exception(exc, *, is_disconnect=None, is_pre_ping=False):
    if exc is None:
        return None
    sqlstate = _sqlstate(exc)
    category = "unknown"
    if isinstance(exc, sqlalchemy.exc.TimeoutError):
        category = "pool_timeout"
    else:
        messages = " ".join(str(item) for item in _iter_exception_chain(exc)).lower()
        if any(message in messages for message in _CLOSED_CONNECTION_MESSAGES):
            category = "connection_closed"
        elif sqlstate in _SQLSTATE_CATEGORIES:
            category = _SQLSTATE_CATEGORIES[sqlstate]
        elif sqlstate and sqlstate.startswith("08"):
            category = "connection_lost"
        elif _ASYNCPG_ERRORS and any(isinstance(item, _ASYNCPG_ERRORS) for item in _iter_exception_chain(exc)):
            category = "connection_closed" if "closed" in messages else "connection_lost"
        elif isinstance(exc, sqlalchemy.exc.DBAPIError):
            category = "other_dbapi_error"
    if is_disconnect is True and category == "unknown":
        category = "connection_lost"
    connection_invalidated = False
    if isinstance(exc, sqlalchemy.exc.DBAPIError):
        connection_invalidated = bool(getattr(exc, "connection_invalidated", False))
    return {
        "error_classification": category,
        "exception_class": type(exc).__name__,
        "exception_module": type(exc).__module__,
        "sqlstate": sqlstate,
        "is_disconnect": bool(is_disconnect) if is_disconnect is not None else False,
        "is_pre_ping": bool(is_pre_ping),
        "connection_invalidated": connection_invalidated,
    }


def _log_db_event(level, event, **fields):
    try:
        safe_fields = {str(key): _safe_log_value(value) for key, value in fields.items()}
        logger.log(
            level,
            "Database pool event: %s",
            event,
            extra={"db_event": event, "correlation_id": _get_correlation_id(), **safe_fields},
        )
    except Exception:
        try:
            logger.log(level, "Database pool event: %s", event)
        except Exception:
            pass


def _install_pool_instrumentation(engine):
    sync_engine = getattr(engine, "sync_engine", engine)
    if id(engine) in _INSTRUMENTED_ENGINES:
        return
    _INSTRUMENTED_ENGINES.add(id(engine))

    @event.listens_for(sync_engine, "handle_error")
    def _handle_error(context):
        try:
            exc = getattr(context, "original_exception", None)
            if exc is None:
                exc = getattr(context, "exception", None)
            classification = _classify_db_exception(
                exc,
                is_disconnect=getattr(context, "is_disconnect", None),
                is_pre_ping=getattr(context, "is_pre_ping", False),
            )
            fields = dict(classification or {})
            dbapi_connection = getattr(context, "connection", None)
            record = getattr(context, "connection_record", None)
            fields.update(
                {
                    "phase": "pre_ping" if getattr(context, "is_pre_ping", False) else "query",
                    "operation": getattr(context, "operation", None),
                    "backend_pid": _backend_pid(dbapi_connection),
                    "record_id": id(record) if record is not None else None,
                    "engine_id": id(sync_engine),
                }
            )
            level = logging.DEBUG
            if classification and (
                classification["error_classification"]
                in {
                    "connection_closed",
                    "connection_lost",
                    "server_shutdown",
                    "cannot_connect_now",
                    "idle_session_timeout",
                    "idle_in_transaction_timeout",
                    "too_many_connections",
                    "pool_timeout",
                    "other_dbapi_error",
                }
                or getattr(context, "is_disconnect", False)
            ):
                level = logging.WARNING
            _log_db_event(level, "dbapi_error", **fields)
        except Exception:
            pass

    @event.listens_for(sync_engine, "connect")
    def _on_connect(dbapi_connection, connection_record):
        try:
            _log_db_event(
                logging.DEBUG,
                "pool_connect",
                backend_pid=_backend_pid(dbapi_connection),
                record_id=id(connection_record) if connection_record is not None else None,
                engine_id=id(sync_engine),
            )
        except Exception:
            pass

    @event.listens_for(sync_engine, "checkout")
    def _on_checkout(dbapi_connection, connection_record, proxy):
        try:
            _log_db_event(
                logging.DEBUG,
                "pool_checkout",
                backend_pid=_backend_pid(dbapi_connection),
                record_id=id(connection_record) if connection_record is not None else None,
                engine_id=id(sync_engine),
            )
        except Exception:
            pass

    @event.listens_for(sync_engine, "checkin")
    def _on_checkin(dbapi_connection, connection_record):
        try:
            _log_db_event(
                logging.DEBUG,
                "pool_checkin",
                backend_pid=_backend_pid(dbapi_connection),
                record_id=id(connection_record) if connection_record is not None else None,
                engine_id=id(sync_engine),
            )
        except Exception:
            pass

    @event.listens_for(sync_engine, "invalidate")
    def _on_invalidate(dbapi_connection, connection_record, exception):
        try:
            classification = _classify_db_exception(exception)
            fields = dict(classification or {})
            fields.update(
                {
                    "backend_pid": _backend_pid(dbapi_connection),
                    "record_id": id(connection_record) if connection_record is not None else None,
                    "engine_id": id(sync_engine),
                }
            )
            _log_db_event(logging.INFO, "pool_invalidate", **fields)
        except Exception:
            pass

    @event.listens_for(sync_engine, "soft_invalidate")
    def _on_soft_invalidate(dbapi_connection, connection_record, exception):
        try:
            classification = _classify_db_exception(exception)
            fields = dict(classification or {})
            fields.update(
                {
                    "backend_pid": _backend_pid(dbapi_connection),
                    "record_id": id(connection_record) if connection_record is not None else None,
                    "engine_id": id(sync_engine),
                }
            )
            _log_db_event(logging.INFO, "pool_soft_invalidate", **fields)
        except Exception:
            pass

    @event.listens_for(sync_engine, "close")
    def _on_close(dbapi_connection, connection_record):
        try:
            _log_db_event(
                logging.DEBUG,
                "pool_close",
                backend_pid=_backend_pid(dbapi_connection),
                record_id=id(connection_record) if connection_record is not None else None,
                engine_id=id(sync_engine),
            )
        except Exception:
            pass


def _log_pool_configuration(engine):
    try:
        url = make_url(str(engine.url))
        host = (url.host or "").lower()
        if "pooler" in host or "pgbouncer" in host:
            topology_hint = "pooled_endpoint_hint"
        elif host.endswith("neon.tech"):
            topology_hint = "neon_direct_hint"
        elif host:
            topology_hint = "direct_or_unknown"
        else:
            topology_hint = "unknown"
        pool = getattr(engine, "pool", None)
        if pool is None:
            pool = getattr(getattr(engine, "sync_engine", None), "pool", None)
        size = _call_if_callable(getattr(pool, "size", None))
        checked_out = _call_if_callable(getattr(pool, "checkedout", None))
        _log_db_event(
            logging.INFO,
            "pool_configuration",
            topology_hint=topology_hint,
            driver=url.drivername,
            pool_class=type(pool).__name__ if pool is not None else None,
            pool_size=size,
            max_overflow=getattr(pool, "_max_overflow", None),
            pool_timeout=getattr(pool, "_timeout", None),
            pool_recycle=getattr(pool, "_recycle", None),
            pool_pre_ping=getattr(pool, "_pre_ping", None),
            checked_out=checked_out,
            app_env=getattr(config_module.settings, "APP_ENV", None),
            engine_id=id(getattr(engine, "sync_engine", engine)),
        )
    except Exception:
        _log_db_event(logging.DEBUG, "pool_configuration", topology_hint="unknown")


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

        db_url = getattr(config_module.settings, "DATABASE_URL", None)
        is_sqlite = False
        is_production = getattr(config_module.settings, "APP_ENV", "development") not in (
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
            logger.warning("DATABASE_URL is missing. Falling back to local SQLite database.")
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
                logger.warning("Configured database is unreachable. Falling back to local SQLite database.")

        if is_sqlite:
            engine = create_async_engine(
                db_url,
                echo=getattr(config_module.settings, "APP_ENV", "development") == "development",
                future=True,
                connect_args={"check_same_thread": False, "timeout": 30.0},
            )

            _install_pool_instrumentation(engine)

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

            _log_pool_configuration(engine)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Successfully created/verified SQLite database schema.")
        else:
            engine_kwargs = {
                "echo": getattr(config_module.settings, "APP_ENV", "development") == "development",
                "future": True,
                "pool_pre_ping": True,
            }
            pool_size = getattr(config_module.settings, "DATABASE_POOL_SIZE", None)
            max_overflow = getattr(config_module.settings, "DATABASE_MAX_OVERFLOW", None)
            pool_timeout = getattr(config_module.settings, "DATABASE_POOL_TIMEOUT", None)
            pool_recycle = getattr(config_module.settings, "DATABASE_POOL_RECYCLE", None)
            if pool_size is not None:
                engine_kwargs["pool_size"] = pool_size
            if max_overflow is not None:
                engine_kwargs["max_overflow"] = max_overflow
            if pool_timeout is not None:
                engine_kwargs["pool_timeout"] = pool_timeout
            if pool_recycle is not None:
                engine_kwargs["pool_recycle"] = pool_recycle

            engine = create_async_engine(db_url, **engine_kwargs)
            _install_pool_instrumentation(engine)
            _log_pool_configuration(engine)

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

        original_classification = _classify_db_exception(exc_val) if exc_val is not None else None

        if exc_val is not None and isinstance(exc_val, sqlalchemy.exc.TimeoutError):
            pool = getattr(getattr(session, "bind", None), "pool", None)
            _log_db_event(
                logging.WARNING,
                "pool_timeout",
                error_classification="pool_timeout",
                original_error_classification=(
                    original_classification["error_classification"] if original_classification else None
                ),
                application_exception_active=True,
                pool_size=_call_if_callable(getattr(pool, "size", None)),
                checked_out=_call_if_callable(getattr(pool, "checkedout", None)),
                backend_pid=None,
            )

        try:
            await session.__aexit__(exc_type, exc_val, exc_tb)
        except Exception as cleanup_exc:
            cleanup_classification = _classify_db_exception(cleanup_exc)
            extra = {}
            if cleanup_classification is not None:
                extra.update(cleanup_classification)
            extra["original_error_classification"] = (
                original_classification["error_classification"] if original_classification else None
            )
            extra["application_exception_active"] = exc_val is not None
            extra = {str(key): _safe_log_value(value) for key, value in extra.items()}
            is_known_closed = (
                cleanup_classification is not None
                and cleanup_classification.get("error_classification") == "connection_closed"
            )
            if is_known_closed:
                logger.warning(
                    "Database session cleanup failed: %s",
                    _sanitize_db_error(cleanup_exc),
                    extra=extra,
                )
            else:
                logger.warning(
                    "Database session cleanup failed: %s",
                    _sanitize_db_error(cleanup_exc),
                    exc_info=True,
                    extra=extra,
                )
            try:
                await session.invalidate()
            except Exception as invalidate_exc:
                logger.warning(
                    "Database session invalidation failed: %s",
                    _sanitize_db_error(invalidate_exc),
                    exc_info=True,
                )
        return False


def AsyncSessionLocal() -> DatabaseSession:
    return DatabaseSession()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    async with _init_lock:
        if _engine is not None:
            _INSTRUMENTED_ENGINES.discard(id(_engine))
            try:
                await _engine.dispose()
            except Exception as exc:
                logger.warning("Engine disposal failed: %s", _sanitize_db_error(exc), exc_info=True)
            finally:
                _engine = None
                _sessionmaker = None
