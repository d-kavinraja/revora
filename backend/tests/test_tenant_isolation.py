"""Tenant isolation regressions (F1/F2/F3/F4).

Cross-tenant access must fail closed with 404 and must never leak other
tenants' repositories, reviews, budgets, or sync-run audit details.
"""
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token
from app.models.github import Installation, PullRequest, Repository
from app.models.review import Review
from app.models.sync_run import SyncRun
from app.models.token_usage import CostBudget
from app.models.user import User

NOW = datetime.now(UTC)


async def _make_user(session, *, email: str, name: str = "User") -> User:
    user = User(
        id=uuid.uuid4(),
        name=name,
        email=email,
        role="user",
        is_verified=True,
        token_version=0,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _seed_installation(session, owner: User, *, installation_id: int = 920001):
    installation = Installation(
        id=uuid.uuid4(),
        installation_id=installation_id,
        account_id=installation_id * 10,
        account_login=f"acct-{owner.email.split('@')[0]}",
        account_type="User",
        user_id=owner.id,
        repository_selection="all",
        permissions={"contents": "read", "pull_requests": "write"},
        events={"pull_request": True},
        app_id=424242,
    )
    session.add(installation)
    await session.commit()
    await session.refresh(installation)
    return installation


async def _seed_repo_and_review(
    session, owner: User, *, installation=None
) -> tuple[Repository, PullRequest, Review]:
    installation = installation or await _seed_installation(session, owner)
    repo = Repository(
        id=uuid.uuid4(),
        github_id=100000 + owner.token_version,
        name="demo",
        full_name=f"{installation.account_login}/demo",
        installation_id=installation.id,
        reviews_enabled=True,
    )
    session.add(repo)
    await session.commit()
    await session.refresh(repo)
    pr = PullRequest(
        id=uuid.uuid4(),
        repo_id=repo.id,
        pr_number=1,
        title="Demo PR",
        author="contributor",
        head_sha="deadbeef" + "0" * 32,
        base_branch="main",
        head_branch="feature",
        status="open",
    )
    session.add(pr)
    await session.commit()
    await session.refresh(pr)
    review = Review(id=uuid.uuid4(), pr_id=pr.id, status="completed")
    session.add(review)
    await session.commit()
    await session.refresh(review)
    return repo, pr, review


def _auth(user: User) -> dict[str, str]:
    token = create_access_token(
        subject=str(user.id), token_version=int(user.token_version or 0)
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def two_users(test_db):
    owner = await _make_user(test_db, email="owner@example.com", name="Owner")
    intruder = await _make_user(test_db, email="intruder@example.com", name="Intruder")
    return owner, intruder


async def test_f1_foreign_repo_sync_returns_404(test_db, anon_client, two_users):
    owner, intruder = two_users
    repo, _, _ = await _seed_repo_and_review(test_db, owner)

    response = anon_client.post(
        f"/api/v1/repositories/{repo.id}/sync", headers=_auth(intruder)
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Repository not found"


async def test_f1_unknown_repo_sync_returns_404(test_db, anon_client, two_users):
    _, intruder = two_users
    response = anon_client.post(
        f"/api/v1/repositories/{uuid.uuid4()}/sync", headers=_auth(intruder)
    )
    assert response.status_code == 404


async def test_f2_foreign_review_verification_returns_404_before_clone(
    test_db, anon_client, two_users
):
    owner, intruder = two_users
    _, _, review = await _seed_repo_and_review(test_db, owner)

    response = anon_client.post(
        "/api/v1/verify/review",
        headers=_auth(intruder),
        json={
            "review_id": str(review.id),
            "repository_url": "https://github.com/owner/demo",
            "ai_response_text": "There is a bug on line 1.",
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Review not found"


async def test_f2_unknown_review_verification_returns_404(
    test_db, anon_client, two_users
):
    _, intruder = two_users
    response = anon_client.post(
        "/api/v1/verify/review",
        headers=_auth(intruder),
        json={
            "review_id": str(uuid.uuid4()),
            "repository_url": "https://github.com/owner/demo",
            "ai_response_text": "Some review text",
        },
    )
    assert response.status_code == 404


async def test_f3_foreign_budget_update_returns_404_and_is_unchanged(
    test_db, anon_client, two_users
):
    owner, intruder = two_users
    budget = CostBudget(
        id=uuid.uuid4(),
        user_id=owner.id,
        budget_type="monthly",
        limit_usd=100.0,
        spent_usd=5.0,
    )
    test_db.add(budget)
    await test_db.commit()

    response = anon_client.put(
        f"/api/v1/platform-usage/budgets/{budget.id}",
        headers=_auth(intruder),
        json={"limit_usd": 1.0},
    )
    assert response.status_code == 404

    refreshed = (
        await test_db.execute(select(CostBudget).where(CostBudget.id == budget.id))
    ).scalar_one()
    assert refreshed.limit_usd == 100.0


async def test_f3_foreign_budget_delete_returns_404_and_is_preserved(
    test_db, anon_client, two_users
):
    owner, intruder = two_users
    budget = CostBudget(
        id=uuid.uuid4(),
        user_id=owner.id,
        budget_type="monthly",
        limit_usd=100.0,
        spent_usd=0.0,
    )
    test_db.add(budget)
    await test_db.commit()

    response = anon_client.delete(
        f"/api/v1/platform-usage/budgets/{budget.id}", headers=_auth(intruder)
    )
    assert response.status_code == 404

    refreshed = (
        await test_db.execute(select(CostBudget).where(CostBudget.id == budget.id))
    ).scalar_one_or_none()
    assert refreshed is not None


async def test_f4_sync_runs_scoped_to_current_user(test_db, anon_client, two_users):
    owner, intruder = two_users
    own_run = SyncRun(
        id=uuid.uuid4(),
        reason="user",
        triggered_by=owner.id,
        started_at=NOW,
        status="completed",
        repo_count=1,
    )
    other_run = SyncRun(
        id=uuid.uuid4(),
        reason="user",
        triggered_by=intruder.id,
        started_at=NOW,
        status="completed",
        repo_count=99,
    )
    system_run = SyncRun(
        id=uuid.uuid4(),
        reason="startup",
        triggered_by=None,
        started_at=NOW,
        status="completed",
        repo_count=500,
    )
    test_db.add_all([own_run, other_run, system_run])
    await test_db.commit()

    response = anon_client.get(
        "/api/v1/repositories/sync-runs", headers=_auth(owner)
    )
    assert response.status_code == 200
    runs = response.json()
    run_ids = {run["id"] for run in runs}
    assert str(own_run.id) in run_ids
    assert str(other_run.id) not in run_ids
    assert str(system_run.id) not in run_ids
