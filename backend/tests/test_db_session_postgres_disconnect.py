import os
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
async def test_idle_terminated_connection_recovers_via_pre_ping():
    url = LOOPBACK_URL
    asyncpg_url = _asyncpg_url(url)

    pid = None
    async with db_session.AsyncSessionLocal() as session:
        await session.execute(text("SELECT 1"))
        pid = (await session.execute(text("SELECT pg_backend_pid()"))).scalar_one()

    killer = await asyncpg.connect(asyncpg_url, ssl=False)
    try:
        await killer.execute("SELECT pg_terminate_backend($1)", pid)
    finally:
        await killer.close()

    async with db_session.AsyncSessionLocal() as session:
        assert (await session.execute(text("SELECT 1"))).scalar_one() == 1


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
