"""Installation/token lifecycle hardening regressions (N1/N2/N3).

Unknown or revoked installations must fail closed before any GitHub token
is requested, and cached installation tokens must not survive revocation.
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (register tables)
from app.core.config import settings
from app.db.base import Base
from app.github.auth import github_app_auth
from app.github.shared import get_or_create_review_records
from app.models.github import Installation, Repository
from app.models.user import User
from app.services.installation_lifecycle import (
    InstallationNotAttemptableError,
    can_attempt_token,
    require_attemptable_installation,
)
from app.services.review_lifecycle import ReviewLifecycleService


def _make_installation(**overrides) -> Installation:
    values = {
        "id": uuid.uuid4(),
        "installation_id": 990001,
        "account_id": 77001,
        "account_login": "hardening-acct",
        "account_type": "User",
        "user_id": uuid.uuid4(),
        "repository_selection": "all",
        "permissions": {"contents": "read", "pull_requests": "write"},
        "events": {"pull_request": True},
        "permissions_ok": True,
        "lifecycle_status": "active",
        "suspended_at": None,
        "retry_after": None,
        "app_id": None,
    }
    values.update(overrides)
    return Installation(**values)


# N1 — cached tokens are dropped on revocation.


def test_n1_invalidate_installation_token_clears_only_that_installation():
    future = datetime.now(UTC) + timedelta(hours=1)

    github_app_auth._token_cache.clear()
    github_app_auth._token_cache[("app-a", 990001)] = ("tok-1", future)
    github_app_auth._token_cache[("app-b", 990001)] = ("tok-2", future)
    github_app_auth._token_cache[("app-a", 990002)] = ("tok-3", future)
    try:
        github_app_auth.invalidate_installation_token(990001)
        assert ("app-a", 990001) not in github_app_auth._token_cache
        assert ("app-b", 990001) not in github_app_auth._token_cache
        assert github_app_auth._token_cache[("app-a", 990002)] == ("tok-3", future)
    finally:
        github_app_auth._token_cache.clear()


# N2 — execution paths fail closed for unknown or non-attemptable installations.


async def test_n2_unknown_installation_is_rejected(test_db, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_APP_ID", None, raising=False)
    with pytest.raises(InstallationNotAttemptableError, match="unknown"):
        await require_attemptable_installation(test_db, 123456789)


async def test_n2_active_installation_is_accepted(test_db, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_APP_ID", None, raising=False)
    owner = User(
        id=uuid.uuid4(),
        name="Owner",
        email="n2-owner@example.com",
        role="user",
        is_verified=True,
    )
    test_db.add(owner)
    await test_db.flush()

    installation = Installation(
        id=uuid.uuid4(),
        installation_id=990201,
        account_id=77002,
        account_login="n2-acct",
        account_type="User",
        user_id=owner.id,
        repository_selection="all",
        permissions={"contents": "read"},
        events={},
        permissions_ok=True,
        lifecycle_status="active",
    )
    test_db.add(installation)
    await test_db.commit()

    result = await require_attemptable_installation(test_db, 990201)
    assert result.id == installation.id


async def test_n2_suspended_installation_is_rejected(test_db, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_APP_ID", None, raising=False)
    owner = User(
        id=uuid.uuid4(),
        name="Owner",
        email="n2-susp@example.com",
        role="user",
        is_verified=True,
    )
    test_db.add(owner)
    await test_db.flush()

    installation = Installation(
        id=uuid.uuid4(),
        installation_id=990202,
        account_id=77003,
        account_login="n2-susp-acct",
        account_type="User",
        user_id=owner.id,
        repository_selection="all",
        permissions={},
        events={},
        permissions_ok=False,
        suspended_at=datetime.now(UTC),
        lifecycle_status="suspended",
    )
    test_db.add(installation)
    await test_db.commit()

    with pytest.raises(InstallationNotAttemptableError):
        await require_attemptable_installation(test_db, 990202)


def test_n2_can_attempt_token_respects_retry_after(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_APP_ID", None, raising=False)
    future = datetime.now(UTC) + timedelta(hours=2)
    past = datetime.now(UTC) - timedelta(hours=2)

    assert can_attempt_token(_make_installation(retry_after=future)) is False
    assert can_attempt_token(_make_installation(retry_after=past)) is True


# N3 — lifecycle actions and record creation refuse removed/revoked targets.


def test_n3_ensure_review_target_usable_rejects_removed_repo(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_APP_ID", None, raising=False)
    repo = Repository(
        id=uuid.uuid4(),
        github_id=880001,
        name="demo",
        full_name="hardening-acct/demo",
        removed_at=datetime.now(UTC),
    )
    installation = _make_installation()

    with pytest.raises(ValueError, match="removed"):
        ReviewLifecycleService._ensure_review_target_usable(
            repo, installation, "rerun"
        )


def test_n3_ensure_review_target_usable_rejects_unattemptable_installation(
    monkeypatch,
):
    monkeypatch.setattr(settings, "GITHUB_APP_ID", None, raising=False)
    repo = Repository(
        id=uuid.uuid4(),
        github_id=880002,
        name="demo",
        full_name="hardening-acct/demo",
        removed_at=None,
    )
    installation = _make_installation(
        suspended_at=datetime.now(UTC), lifecycle_status="suspended"
    )

    with pytest.raises(ValueError, match="installation"):
        ReviewLifecycleService._ensure_review_target_usable(
            repo, installation, "cancel"
        )


def test_n3_ensure_review_target_usable_accepts_valid_target(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_APP_ID", None, raising=False)
    repo = Repository(
        id=uuid.uuid4(),
        github_id=880003,
        name="demo",
        full_name="hardening-acct/demo",
        removed_at=None,
    )
    installation = _make_installation()

    ReviewLifecycleService._ensure_review_target_usable(
        repo, installation, "rerun"
    )


async def test_n3_get_or_create_review_records_refuses_removed_repo(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_APP_ID", None, raising=False)
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    monkeypatch.setattr("app.github.shared.AsyncSessionLocal", factory)

    owner_id = uuid.uuid4()
    async with factory() as db:
        owner = User(
            id=owner_id,
            name="Owner",
            email="n3-owner@example.com",
            role="user",
            is_verified=True,
        )
        db.add(owner)
        await db.flush()
        installation = Installation(
            id=uuid.uuid4(),
            installation_id=990301,
            account_id=77004,
            account_login="n3-acct",
            account_type="User",
            user_id=owner_id,
            repository_selection="all",
            permissions={"contents": "read"},
            events={},
            permissions_ok=True,
            lifecycle_status="active",
        )
        db.add(installation)
        await db.flush()
        repo = Repository(
            id=uuid.uuid4(),
            github_id=880004,
            name="demo",
            full_name="n3-acct/demo",
            installation_id=installation.id,
            removed_at=datetime.now(UTC),
        )
        db.add(repo)
        await db.commit()

    with pytest.raises(ValueError, match="removed"):
        await get_or_create_review_records(
            installation_id=990301,
            repository={"id": 880004, "name": "demo", "full_name": "n3-acct/demo"},
            pull_request={
                "number": 7,
                "head": {"sha": "a" * 40},
                "title": "Demo",
                "user": {"login": "author"},
                "base": {"ref": "main"},
            },
            delivery_id=f"delivery-{uuid.uuid4()}",
        )

    await engine.dispose()
