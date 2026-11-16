
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import config as config_module
from app.db import session as db_session


@pytest.fixture(autouse=True)
def _reset_engine():
    db_session._engine = None
    db_session._sessionmaker = None
    db_session._INSTRUMENTED_ENGINES.clear()
    yield
    db_session._engine = None
    db_session._sessionmaker = None
    db_session._INSTRUMENTED_ENGINES.clear()


@pytest.mark.asyncio
async def test_get_db_yields_real_async_session(monkeypatch):
    monkeypatch.setattr(config_module.settings, "APP_ENV", "testing", raising=False)
    monkeypatch.setattr(config_module.settings, "DATABASE_URL", "sqlite+aiosqlite:///:memory:", raising=False)

    async for session in db_session.get_db():
        assert isinstance(session, AsyncSession)


@pytest.mark.asyncio
async def test_session_closes_exactly_once(monkeypatch):
    monkeypatch.setattr(config_module.settings, "APP_ENV", "testing", raising=False)
    monkeypatch.setattr(config_module.settings, "DATABASE_URL", "sqlite+aiosqlite:///:memory:", raising=False)

    calls = []

    original = AsyncSession.__aexit__

    async def spy(self, *args, **kwargs):
        calls.append(1)
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "__aexit__", spy)

    async for _ in db_session.get_db():
        pass

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_original_exception_survives_cleanup(monkeypatch):
    monkeypatch.setattr(config_module.settings, "APP_ENV", "testing", raising=False)
    monkeypatch.setattr(config_module.settings, "DATABASE_URL", "sqlite+aiosqlite:///:memory:", raising=False)

    async def boom(self, *args, **kwargs):
        raise RuntimeError("cleanup boom")

    monkeypatch.setattr(AsyncSession, "__aexit__", boom)

    with pytest.raises(ValueError, match="original boom"):
        async for _ in db_session.get_db():
            raise ValueError("original boom")


@pytest.mark.asyncio
async def test_production_no_sqlite_fallback(monkeypatch):
    monkeypatch.setattr(config_module.settings, "APP_ENV", "production", raising=False)
    monkeypatch.setattr(
        config_module.settings,
        "DATABASE_URL",
        "postgresql+asyncpg://u:p@127.0.0.1:1/db",
        raising=False,
    )
    monkeypatch.setattr(db_session, "is_db_connectable", lambda url: False)

    with pytest.raises(RuntimeError):
        await db_session.get_engine_and_sessionmaker()


@pytest.mark.asyncio
async def test_development_sqlite_fallback_allowed(monkeypatch):
    monkeypatch.setattr(config_module.settings, "APP_ENV", "development", raising=False)
    monkeypatch.setattr(
        config_module.settings,
        "DATABASE_URL",
        "postgresql+asyncpg://u:p@127.0.0.1:1/db",
        raising=False,
    )
    monkeypatch.setattr(db_session, "is_db_connectable", lambda url: False)

    engine, sm = await db_session.get_engine_and_sessionmaker()
    assert engine is not None
    assert sm is not None
    await db_session.dispose_engine()


@pytest.mark.asyncio
async def test_engine_disposal_idempotent(monkeypatch):
    monkeypatch.setattr(config_module.settings, "APP_ENV", "testing", raising=False)
    monkeypatch.setattr(config_module.settings, "DATABASE_URL", "sqlite+aiosqlite:///:memory:", raising=False)

    await db_session.get_engine_and_sessionmaker()
    await db_session.dispose_engine()
    assert db_session._engine is None
    # second call should not raise
    await db_session.dispose_engine()


import asyncpg
from sqlalchemy.exc import TimeoutError


@pytest.mark.asyncio
async def test_classifier_maps_closed_connection(monkeypatch):
    exc = asyncpg.exceptions.InterfaceError("underlying connection is closed")
    result = db_session._classify_db_exception(exc)
    assert result["error_classification"] == "connection_closed"


@pytest.mark.asyncio
async def test_classifier_maps_sqlstate_and_timeout(monkeypatch):
    class IdleError(Exception):
        sqlstate = "57P05"

    assert db_session._classify_db_exception(IdleError("idle"))["error_classification"] == "idle_session_timeout"
    assert db_session._classify_db_exception(TimeoutError("pool"))["error_classification"] == "pool_timeout"


@pytest.mark.asyncio
async def test_sanitizer_redacts_secrets(monkeypatch):
    text = db_session._sanitize_db_error(
        Exception("postgresql://user:secret@db.example.com/revora password=hunter2 [SQL: SELECT 1] [parameters: (1,)]")
    )
    assert "secret" not in text
    assert "hunter2" not in text
    assert "redacted-url" in text
    assert "password=[redacted]" in text


@pytest.mark.asyncio
async def test_pool_configuration_log_does_not_leak_url(monkeypatch, caplog):
    monkeypatch.setattr(config_module.settings, "APP_ENV", "testing", raising=False)
    monkeypatch.setattr(config_module.settings, "DATABASE_URL", "sqlite+aiosqlite:///:memory:", raising=False)

    caplog.set_level("INFO")
    engine, _ = await db_session.get_engine_and_sessionmaker()
    assert engine is not None
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "redacted-url" not in messages
    assert "sqlite+aiosqlite" not in messages
    await db_session.dispose_engine()
