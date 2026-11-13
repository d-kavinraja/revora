
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import config as config_module
from app.db import session as db_session


@pytest.fixture(autouse=True)
def _reset_engine():
    db_session._engine = None
    db_session._sessionmaker = None
    yield
    db_session._engine = None
    db_session._sessionmaker = None


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
