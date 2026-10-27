import asyncio
from collections.abc import AsyncGenerator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.auth import create_access_token, get_password_hash
from app.core.deps import get_current_user
from app.core.deps_admin import ADMIN_SESSION_COOKIE
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.admin import AdminUser
from app.models.user import User
from app.services.admin_auth import create_admin_session

# Use an in-memory SQLite database for testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Enable SQLite WAL and now() function for tests
    import datetime

    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "connect")
    def configure_sqlite_connection(dbapi_connection, connection_record):
        dbapi_connection.create_function(
            "now", 0, lambda: datetime.datetime.now(datetime.UTC).isoformat()
        )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine
    await engine.dispose()


@pytest.fixture
async def test_db(test_engine) -> AsyncGenerator[AsyncSession, None]:
    connection = await test_engine.connect()
    transaction = await connection.begin()

    SessionLocal = async_sessionmaker(
        bind=connection, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )

    async with SessionLocal() as session:
        yield session

    await transaction.rollback()
    await connection.close()


@pytest.fixture
async def mock_user(test_db) -> User:
    import uuid

    user = User(
        id=uuid.uuid4(),
        name="Test User",
        email="test@example.com",
        role="user",
        is_verified=True,
    )
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


@pytest.fixture
def client(test_db, mock_user) -> TestClient:
    # Override dependencies
    async def override_get_db():
        yield test_db

    async def override_get_current_user():
        return mock_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    with TestClient(app) as test_client:
        yield test_client

    # Clear overrides
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Admin control-center fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_platform_settings():
    """Keep maintenance state from bleeding across tests.

    The maintenance middleware consults `platform_settings_service` on every
    API request. Without isolation the TTL cache could leak `enabled=true`
    into unrelated suites, and the `db_factory` fallback would open a real
    session against the (unmocked) app database. Tests that exercise
    maintenance seed state via `set_maintenance(test_db, ...)`, which primes
    the write-through cache.
    """
    from app.services.platform_settings import platform_settings_service

    platform_settings_service.clear_cache()
    original_factory = platform_settings_service.db_factory
    platform_settings_service.db_factory = None
    yield
    platform_settings_service.db_factory = original_factory
    platform_settings_service.clear_cache()


@pytest.fixture
async def admin_user(test_db) -> AdminUser:
    admin = AdminUser(
        username="testadmin",
        password_hash=get_password_hash("admin-test-password"),
        is_active=True,
    )
    test_db.add(admin)
    await test_db.commit()
    await test_db.refresh(admin)
    return admin


@pytest.fixture
async def admin_session_cookie(test_db, admin_user) -> str:
    """Raw opaque token for a valid, persisted admin session."""
    raw_token, _ = await create_admin_session(
        test_db,
        admin=admin_user,
        ip_address="127.0.0.1",
        user_agent="pytest",
    )
    await test_db.commit()
    return raw_token


@pytest.fixture
async def user_auth_token(test_db, mock_user) -> str:
    return create_access_token(
        subject=str(mock_user.id),
        token_version=int(getattr(mock_user, "token_version", 0) or 0),
    )


@pytest.fixture
def anon_client(test_db) -> TestClient:
    """TestClient with `get_db` overridden but REAL auth dependencies.

    Unlike `client`, no `get_current_user` override is installed, so admin
    tests exercise actual cookie/token resolution. Use for admin authz,
    lockout and cross-namespace isolation tests.
    """

    async def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def admin_client(anon_client, admin_session_cookie) -> TestClient:
    """`anon_client` carrying a valid admin session cookie."""
    anon_client.cookies.set(ADMIN_SESSION_COOKIE, admin_session_cookie)
    return anon_client
