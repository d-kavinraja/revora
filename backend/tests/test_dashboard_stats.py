"""User dashboard — Issues Caught accuracy.

Scope, dedup and availability tests for GET /api/v1/dashboard/stats, checked
directly against the persisted ``verification_results`` rows. All fixtures are
disposable (in-memory SQLite via ``test_db``); no production data is touched.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (register tables)
from app.api.v1.endpoints.dashboard import get_dashboard_stats
from app.db.base import Base
from app.models.execution import ReviewExecution
from app.models.github import Installation, PullRequest, Repository
from app.models.review import Review
from app.models.user import User
from app.models.verification import VerificationResultModel


async def _user(db: AsyncSession, email: str) -> User:
    user = User(
        id=uuid.uuid4(),
        name="Dash User",
        email=email,
        role="user",
        is_verified=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _scaffold(
    db: AsyncSession,
    user: User,
    *,
    installation_id: int,
    account: str = "owner",
    repo_name: str = "repo",
    removed_at: datetime | None = None,
):
    installation = Installation(
        id=uuid.uuid4(),
        installation_id=installation_id,
        account_id=installation_id + 1000,
        account_login=account,
        account_type="User",
        user_id=user.id,
        repository_selection="all",
        permissions={},
        events={},
        permissions_ok=True,
    )
    db.add(installation)
    repo = Repository(
        id=uuid.uuid4(),
        github_id=installation_id + 5000,
        name=repo_name,
        full_name=f"{account}/{repo_name}",
        installation_id=installation.id,
        reviews_enabled=True,
        removed_at=removed_at,
    )
    db.add(repo)
    pr = PullRequest(
        id=uuid.uuid4(),
        repo_id=repo.id,
        pr_number=1,
        title="PR title",
        author=account,
        head_sha="a" * 40,
        base_branch="main",
        head_branch="feature",
        status="open",
    )
    db.add(pr)
    review = Review(id=uuid.uuid4(), pr_id=pr.id, status="completed")
    db.add(review)
    await db.commit()
    return {"installation": installation, "repo": repo, "pr": pr, "review": review}


def _finding(
    review_id,
    *,
    file_path="app/main.py",
    line_number: int | None = 10,
    category="BUG",
    severity="HIGH",
    is_verified=True,
    finding_id=None,
    description="Something is wrong here",
    execution_id=None,
):
    return VerificationResultModel(
        id=uuid.uuid4(),
        review_id=review_id,
        execution_id=execution_id,
        finding_id=finding_id or str(uuid.uuid4()),
        file_path=file_path,
        line_number=line_number,
        category=category,
        severity=severity,
        title="Finding",
        description=description,
        is_verified=is_verified,
        confidence_score=0.9,
    )


async def test_zero_findings_is_a_genuine_zero(test_db):
    user = await _user(test_db, "zero@example.com")
    await _scaffold(test_db, user, installation_id=9101)

    stats = await get_dashboard_stats(test_db, user)

    assert stats["issues_caught_available"] is True
    assert stats["issues_caught_reason"] is None
    assert stats["total_issues_caught"] == 0
    assert stats["suggestions_count"] == 0
    assert stats["critical_count"] == 0
    assert stats["high_count"] == 0
    assert stats["medium_count"] == 0
    assert stats["low_count"] == 0


async def test_single_verified_finding(test_db):
    user = await _user(test_db, "one@example.com")
    scaffold = await _scaffold(test_db, user, installation_id=9102)
    test_db.add(_finding(scaffold["review"].id, severity="HIGH"))
    await test_db.commit()

    stats = await get_dashboard_stats(test_db, user)

    assert stats["issues_caught_available"] is True
    assert stats["total_issues_caught"] == 1
    assert stats["high_count"] == 1
    assert stats["critical_count"] == 0
    assert stats["suggestions_count"] == 0


async def test_multiple_severities_breakdown(test_db):
    user = await _user(test_db, "multi@example.com")
    scaffold = await _scaffold(test_db, user, installation_id=9103)
    review_id = scaffold["review"].id
    test_db.add_all(
        [
            _finding(review_id, line_number=1, category="BUG", severity="CRITICAL"),
            _finding(review_id, line_number=2, category="SECURITY", severity="HIGH"),
            _finding(review_id, line_number=3, category="PERFORMANCE", severity="MEDIUM"),
            _finding(review_id, line_number=4, category="BUG", severity="LOW"),
        ]
    )
    await test_db.commit()

    stats = await get_dashboard_stats(test_db, user)

    assert stats["total_issues_caught"] == 4
    assert stats["critical_count"] == 1
    assert stats["high_count"] == 1
    assert stats["medium_count"] == 1
    assert stats["low_count"] == 1


async def test_rejected_findings_not_counted(test_db):
    user = await _user(test_db, "rejected@example.com")
    scaffold = await _scaffold(test_db, user, installation_id=9104)
    test_db.add_all(
        [
            _finding(scaffold["review"].id, is_verified=False, severity="HIGH"),
            _finding(
                scaffold["review"].id,
                line_number=99,
                is_verified=False,
                category="SECURITY",
                severity="CRITICAL",
            ),
        ]
    )
    await test_db.commit()

    stats = await get_dashboard_stats(test_db, user)

    assert stats["total_issues_caught"] == 0
    assert stats["suggestions_count"] == 0


async def test_rerun_same_issue_is_deduplicated(test_db):
    """A finding re-detected by a rerun must not be double-counted."""
    user = await _user(test_db, "rerun@example.com")
    scaffold = await _scaffold(test_db, user, installation_id=9105)
    review_id = scaffold["review"].id
    execution_1 = ReviewExecution(
        id=uuid.uuid4(),
        review_id=review_id,
        execution_number=1,
        trigger="webhook",
        status="completed",
        started_at=datetime(2026, 11, 1, tzinfo=UTC),
    )
    execution_2 = ReviewExecution(
        id=uuid.uuid4(),
        review_id=review_id,
        execution_number=2,
        trigger="rerun",
        status="completed",
        started_at=datetime(2026, 11, 2, tzinfo=UTC),
    )
    test_db.add_all([execution_1, execution_2])
    test_db.add_all(
        [
            _finding(
                review_id,
                finding_id="run-1",
                execution_id=execution_1.id,
                severity="MEDIUM",
            ),
            _finding(
                review_id,
                finding_id="run-2",
                execution_id=execution_2.id,
                severity="HIGH",
            ),
        ]
    )
    await test_db.commit()

    stats = await get_dashboard_stats(test_db, user)

    # Same (file, line, category) from two runs → one unique issue; the
    # stronger severity (HIGH) is kept for the breakdown.
    assert stats["total_issues_caught"] == 1
    assert stats["high_count"] == 1


async def test_distinct_findings_same_review_count_separately(test_db):
    user = await _user(test_db, "distinct@example.com")
    scaffold = await _scaffold(test_db, user, installation_id=9106)
    review_id = scaffold["review"].id
    test_db.add_all(
        [
            _finding(review_id, line_number=10, category="BUG"),
            _finding(review_id, line_number=11, category="BUG"),
            _finding(review_id, line_number=10, category="SECURITY"),
        ]
    )
    await test_db.commit()

    stats = await get_dashboard_stats(test_db, user)

    assert stats["total_issues_caught"] == 3


async def test_legacy_findings_without_execution_id_count(test_db):
    user = await _user(test_db, "legacy@example.com")
    scaffold = await _scaffold(test_db, user, installation_id=9107)
    review_id = scaffold["review"].id
    test_db.add(
        _finding(
            review_id,
            line_number=20,
            category="BUG",
            severity="MEDIUM",
            execution_id=None,
        )
    )
    await test_db.commit()

    stats = await get_dashboard_stats(test_db, user)

    assert stats["total_issues_caught"] == 1
    assert stats["medium_count"] == 1


async def test_removed_repository_history_preserved(test_db):
    user = await _user(test_db, "removed@example.com")
    scaffold = await _scaffold(
        test_db,
        user,
        installation_id=9108,
        removed_at=datetime(2026, 11, 1, tzinfo=UTC),
    )
    test_db.add(_finding(scaffold["review"].id, severity="HIGH"))
    await test_db.commit()

    stats = await get_dashboard_stats(test_db, user)

    # Removed repos no longer count as connected, but their history persists.
    assert stats["connected_repos"] == 0
    assert stats["total_issues_caught"] == 1


async def test_cross_user_data_isolation(test_db):
    user_a = await _user(test_db, "usera@example.com")
    user_b = await _user(test_db, "userb@example.com")
    scaffold_a = await _scaffold(test_db, user_a, installation_id=9109, account="ownera")
    scaffold_b = await _scaffold(test_db, user_b, installation_id=9110, account="ownerb")
    test_db.add_all(
        [
            _finding(scaffold_a["review"].id, line_number=1, severity="HIGH"),
            _finding(scaffold_a["review"].id, line_number=2, severity="LOW"),
            _finding(scaffold_b["review"].id, line_number=3, severity="CRITICAL"),
        ]
    )
    await test_db.commit()

    stats_a = await get_dashboard_stats(test_db, user_a)
    stats_b = await get_dashboard_stats(test_db, user_b)

    assert stats_a["total_issues_caught"] == 2
    assert stats_a["high_count"] == 1
    assert stats_b["total_issues_caught"] == 1
    assert stats_b["critical_count"] == 1


async def test_improvements_are_suggestions_not_issues(test_db):
    user = await _user(test_db, "suggestions@example.com")
    scaffold = await _scaffold(test_db, user, installation_id=9111)
    test_db.add(_finding(scaffold["review"].id, category="IMPROVEMENT", severity="LOW"))
    await test_db.commit()

    stats = await get_dashboard_stats(test_db, user)

    assert stats["total_issues_caught"] == 0
    assert stats["suggestions_count"] == 1


async def test_engine_persists_execution_id_on_findings(monkeypatch):
    """_persist_to_db attaches the originating execution to every finding row."""

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )

    from app.verification import engine as verification_engine_module
    from app.verification.engine import VerificationEngine

    monkeypatch.setattr(verification_engine_module, "AsyncSessionLocal", factory)

    installation_id = 9112
    async with factory() as db:
        user = await _user(db, "engine@example.com")
        installation = Installation(
            id=uuid.uuid4(),
            installation_id=installation_id,
            account_id=installation_id + 1000,
            account_login="engine-owner",
            account_type="User",
            user_id=user.id,
            repository_selection="all",
            permissions={},
            events={},
            permissions_ok=True,
        )
        repo = Repository(
            id=uuid.uuid4(),
            github_id=installation_id + 5000,
            name="engine-repo",
            full_name="engine-owner/engine-repo",
            installation_id=installation.id,
            reviews_enabled=True,
        )
        pr = PullRequest(
            id=uuid.uuid4(),
            repo_id=repo.id,
            pr_number=1,
            title="PR",
            author="engine-owner",
            head_sha="b" * 40,
            base_branch="main",
            head_branch="feature",
            status="open",
        )
        review = Review(id=uuid.uuid4(), pr_id=pr.id, status="completed")
        db.add_all([installation, repo, pr, review])
        execution = ReviewExecution(
            id=uuid.uuid4(),
            review_id=review.id,
            execution_number=7,
            trigger="rerun",
            status="completed",
            started_at=datetime(2026, 11, 3, tzinfo=UTC),
        )
        db.add(execution)
        await db.commit()
        review_id = review.id
        execution_id = execution.id

    metrics = {
        "total_findings": 1,
        "verified_findings": 1,
        "rejected_findings": 0,
        "hallucinations_detected": 0,
        "false_positives_filtered": 0,
        "avg_confidence": 0.9,
        "verification_duration_ms": 10,
        "hallucination_reports": [],
        "false_positive_reports": [],
    }
    verified_findings = [
        {
            "id": "engine-finding-1",
            "title": "Engine finding",
            "file_path": "app/service.py",
            "line_number": 42,
            "category": "BUG",
            "severity": "HIGH",
            "description": "Bug in service",
            "suggested_fix": "Fix it",
            "confidence": 0.9,
            "evidence": [
                {"evidence_type": "SNIPPET", "content": "snippet", "metadata": {}}
            ],
        }
    ]

    engine_instance = VerificationEngine()
    await engine_instance._persist_to_db(
        review_id, verified_findings, metrics, execution_id=execution_id
    )

    async with factory() as db:
        rows = (
            await db.execute(
                select(VerificationResultModel.execution_id).where(
                    VerificationResultModel.review_id == review_id
                )
            )
        ).all()

    assert len(rows) == 1
    assert rows[0][0] == execution_id

    await engine.dispose()
