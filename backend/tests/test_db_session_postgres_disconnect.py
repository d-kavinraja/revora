import asyncio
import os
import time
from urllib.parse import urlparse

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from app.core import config as config_module
from app.db import session as db_session


def _loopback_postgres_url():
    url = os.getenv("REVORA_TEST_POSTGRES_URL")
    if not url:
        try:
            url = config_module.settings.DATABASE_URL
        except Exception:
            return None
    if not url or not url.startswith(("postgresql", "postgres")):
        return None
    cleaned = url.split("://", 1)[-1]
    if "@" in cleaned:
        cleaned = cleaned.rsplit("@", 1)[-1]
    host = (urlparse("http://" + cleaned).hostname or "").lower()
    if host not in {"localhost", "127.0.0.1", "::1"}:
        return None
    return url


def _asyncpg_url(url):
    return url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg://", "postgresql://")


async def _current_backend_pid() -> int:
    async with db_session.AsyncSessionLocal() as session:
        return (await session.execute(text("SELECT pg_backend_pid()"))).scalar_one()


async def _terminate_and_wait(asyncpg_url: str, pid: int, *, timeout: float = 10.0) -> None:
    """Terminate one backend and wait until PostgreSQL has finished doing it.

    ``pg_terminate_backend`` only signals the backend; the target can still be
    sending its termination error while the client starts the next operation.
    Waiting for the pid to leave ``pg_stat_activity`` makes the test exercise a
    genuinely idle, already-terminated connection instead of racing the shutdown.
    """
    killer = await asyncpg.connect(asyncpg_url, ssl=False)
    try:
        assert await killer.fetchval("SELECT pg_terminate_backend($1)", pid) is True
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = await killer.fetchval(
                "SELECT count(*) FROM pg_stat_activity WHERE pid = $1", pid
            )
            if not remaining:
                return
            await asyncio.sleep(0.01)
        raise AssertionError(f"backend {pid} did not terminate within {timeout}s")
    finally:
        await killer.close()


LOOPBACK_URL = _loopback_postgres_url()


pytestmark = pytest.mark.skipif(LOOPBACK_URL is None, reason="loopback PostgreSQL is required")


@pytest.fixture(autouse=True)
async def _reset_engine():
    db_session._engine = None
    db_session._sessionmaker = None
    db_session._INSTRUMENTED_ENGINES.clear()
    yield
    await db_session.dispose_engine()
    db_session._engine = None
    db_session._sessionmaker = None
    db_session._INSTRUMENTED_ENGINES.clear()


@pytest.mark.asyncio
async def test_closed_connection_cleanup_is_safe_and_pool_recovers(caplog):
    url = LOOPBACK_URL
    asyncpg_url = _asyncpg_url(url)
    caplog.set_level("WARNING", logger="app.db.session")

    async with db_session.AsyncSessionLocal() as session:
        await session.execute(text("SELECT 1"))
        pid = (await session.execute(text("SELECT pg_backend_pid()"))).scalar_one()
        killer = await asyncpg.connect(asyncpg_url, ssl=False)
        try:
            await killer.execute("SELECT pg_terminate_backend($1)", pid)
        finally:
            await killer.close()

    assert any(
        "connection_closed" == getattr(record, "error_classification", None)
        or "cleanup failed" in record.getMessage()
        for record in caplog.records
    )

    async with db_session.AsyncSessionLocal() as session:
        assert (await session.execute(text("SELECT 1"))).scalar_one() == 1


@pytest.mark.asyncio
async def test_pool_events_are_emitted(caplog):
    caplog.set_level("DEBUG", logger="app.db.session")

    async with db_session.AsyncSessionLocal() as session:
        await session.execute(text("SELECT 1"))

    await db_session.dispose_engine()

    events = {getattr(record, "db_event", None) for record in caplog.records}
    assert {"pool_connect", "pool_checkout", "pool_checkin"}.issubset(events)


@pytest.mark.asyncio
async def test_idle_terminated_connection_recovers_via_pre_ping(caplog):
    caplog.set_level("INFO", logger="app.db.session")
    pid = await _current_backend_pid()

    await _terminate_and_wait(_asyncpg_url(LOOPBACK_URL), pid)

    async with db_session.AsyncSessionLocal() as session:
        assert (await session.execute(text("SELECT 1"))).scalar_one() == 1
        recovered_pid = (
            await session.execute(text("SELECT pg_backend_pid()"))
        ).scalar_one()

    assert recovered_pid != pid, "pre-ping must reconnect instead of reusing the dead backend"
    assert any(
        getattr(record, "db_event", None) == "pool_invalidate"
        for record in caplog.records
    ), "the terminated connection must be invalidated, not silently reused"


@pytest.mark.asyncio
async def test_pre_ping_recovers_from_client_protocol_state_error(monkeypatch, caplog):
    """A terminated backend can surface as an asyncpg client-state error.

    asyncpg 0.31 raises ``InternalClientError('cannot switch to state 15; another
    operation (2) is in progress')`` when the server's termination response lands
    while the client starts the next protocol operation. Pre-ping must treat that
    as a dead connection: invalidate it and retry on a fresh one, rather than
    failing the request with that opaque error.
    """
    from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_connection

    caplog.set_level("INFO", logger="app.db.session")
    pid = await _current_backend_pid()
    original_ping = AsyncAdapt_asyncpg_connection.ping
    calls = {"count": 0}

    def flaky_ping(self):
        calls["count"] += 1
        if calls["count"] == 1:
            raise asyncpg.exceptions.InternalClientError(
                "cannot switch to state 15; another operation (2) is in progress"
            )
        return original_ping(self)

    monkeypatch.setattr(AsyncAdapt_asyncpg_connection, "ping", flaky_ping)

    async with db_session.AsyncSessionLocal() as session:
        assert (await session.execute(text("SELECT 1"))).scalar_one() == 1
        recovered_pid = (
            await session.execute(text("SELECT pg_backend_pid()"))
        ).scalar_one()

    # The failed ping invalidates the pooled connection; the retry runs on a
    # brand-new connection, which is fresh and therefore skips pre-ping.
    assert calls["count"] == 1, "pre-ping must be attempted exactly once"
    assert recovered_pid != pid, "the failed connection must be replaced"
    assert any(
        getattr(record, "db_event", None) == "pool_invalidate"
        for record in caplog.records
    ), "a failed pre-ping must invalidate the pooled connection"


def test_internal_client_state_error_is_classified_as_connection_failure():
    exc = asyncpg.exceptions.InternalClientError(
        "cannot switch to state 15; another operation (2) is in progress"
    )
    classification = db_session._classify_db_exception(exc)
    assert classification["error_classification"] in {
        "connection_lost",
        "connection_closed",
    }


@pytest.mark.asyncio
async def test_pool_timeout_is_classified_at_boundary(monkeypatch, caplog):
    monkeypatch.setattr(config_module.settings, "DATABASE_POOL_SIZE", 1, raising=False)
    monkeypatch.setattr(config_module.settings, "DATABASE_MAX_OVERFLOW", 0, raising=False)
    monkeypatch.setattr(config_module.settings, "DATABASE_POOL_TIMEOUT", 0.1, raising=False)

    caplog.set_level("WARNING", logger="app.db.session")

    async with db_session.AsyncSessionLocal() as first:
        await first.execute(text("SELECT 1"))
        with pytest.raises(SQLAlchemyTimeoutError):
            async with db_session.AsyncSessionLocal() as second:
                await second.execute(text("SELECT 1"))

    assert any(
        getattr(record, "error_classification", None) == "pool_timeout"
        or "pool_timeout" in record.getMessage()
        for record in caplog.records
    )
