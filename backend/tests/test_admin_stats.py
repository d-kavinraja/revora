"""Phase 2 read-only analytics tests (plan §22: B11-B13, B30, S6 subset).

Seeded fixture: 4 users (1 disabled, 1 outside the window) / 2 providers /
4 credentials / 5 repositories (1 removed) / 5 pull requests / 5 reviews
(7 executions — two retried) / 2 provider-health snapshots / 1 flag.

Deterministic expectations (window 2026-10-01 → 2026-10-16 UTC):
- reviews counted as 5 logical reviews, retries reported separately as 2
- latest-execution provider/model: openai/gpt-4o ×2, groq/llama ×1,
  openai/gpt-4o-mini ×1, unrecorded ×1
- durations [100, 200, 300] → p50 200.0, p95 290.0
- latest-execution failure rate 1/5; sanitized categories {rate limit: 1}
"""

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event

from app.models.api_key import ApiKey
from app.models.execution import ReviewExecution
from app.models.github import Installation, PullRequest, Repository
from app.models.health import ProviderHealth
from app.models.platform import FeatureFlag, ModelOverride
from app.models.provider import ProviderRegistry
from app.models.review import Review
from app.models.user import User
from app.services import admin_stats

WINDOW_START = datetime(2026, 10, 1, tzinfo=UTC)
WINDOW_END = datetime(2026, 10, 16, tzinfo=UTC)
INSIDE = datetime(2026, 10, 5, 10, 0, 0, tzinfo=UTC)

OVERVIEW_URL = "/api/v1/admin/overview"


@pytest.fixture
async def seeded(test_db) -> dict:
    """Deterministic analytics fixture (see module docstring)."""
    ada = User(
        name="Ada Lovelace",
        email="ada@example.com",
        github_username="ada",
        role="user",
        is_verified=True,
        status="active",
        created_at=INSIDE,
    )
    grace = User(
        name="Grace Hopper",
        email="grace@example.com",
        github_username="grace",
        role="user",
        is_verified=True,
        status="active",
        created_at=INSIDE,
    )
    alan = User(
        name="Alan Turing",
        email="alan@example.com",
        github_username=None,
        role="user",
        is_verified=True,
        status="disabled",
        disabled_at=INSIDE,
        created_at=INSIDE,
    )
    early = User(
        name="Early Bird",
        email="early@example.com",
        role="user",
        is_verified=True,
        status="active",
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    test_db.add_all([ada, grace, alan, early])

    openai = ProviderRegistry(
        name="OpenAI",
        display_name="OpenAI",
        slug="openai",
        litellm_provider="openai",
        default_model="gpt-4o",
        is_enabled=True,
        status="available",
    )
    groq = ProviderRegistry(
        name="Groq",
        display_name="Groq",
        slug="groq",
        litellm_provider="groq",
        default_model="llama-3.3-70b",
        is_enabled=False,
        status="unavailable",
        status_message="provider maintenance",
    )
    test_db.add_all([openai, groq])
    await test_db.commit()

    test_db.add(
        ModelOverride(
            provider_slug="openai",
            model_id="gpt-4o-mini",
            status="unavailable",
            message="sunset",
        )
    )

    inst_ada = Installation(
        installation_id=1001,
        account_id=501,
        account_login="ada-org",
        account_type="User",
        user_id=ada.id,
        repository_selection="all",
        permissions={},
        events={},
        permissions_ok=True,
    )
    inst_grace = Installation(
        installation_id=1002,
        account_id=502,
        account_login="grace-org",
        account_type="User",
        user_id=grace.id,
        repository_selection="all",
        permissions={},
        events={},
        permissions_ok=True,
    )
    test_db.add_all([inst_ada, inst_grace])
    await test_db.commit()

    k_ada_openai = ApiKey(
        user_id=ada.id,
        provider="openai",
        encrypted_key="encrypted-blob-ada-openai",
        label="primary",
        is_valid=True,
        is_enabled=True,
    )
    k_ada_openai_invalid = ApiKey(
        user_id=ada.id,
        provider="openai",
        encrypted_key="encrypted-blob-ada-old",
        label="old",
        is_valid=False,
        is_enabled=True,
    )
    k_ada_groq = ApiKey(
        user_id=ada.id,
        provider="groq",
        encrypted_key="encrypted-blob-ada-groq",
        label="groq",
        is_valid=True,
        is_enabled=False,
    )
    k_grace_openai = ApiKey(
        user_id=grace.id,
        provider="openai",
        encrypted_key="encrypted-blob-grace",
        label="grace-key",
        is_valid=True,
        is_enabled=True,
    )
    test_db.add_all(
        [k_ada_openai, k_ada_openai_invalid, k_ada_groq, k_grace_openai]
    )
    await test_db.commit()

    r_one = Repository(
        github_id=9001,
        name="repo-one",
        full_name="ada/repo-one",
        installation_id=inst_ada.id,
        removed_at=None,
        created_at=INSIDE,
        settings={
            "assigned_provider": "openai",
            "assigned_model": "gpt-4o",
            "assigned_key_id": str(k_ada_openai.id),
        },
    )
    r_two = Repository(
        github_id=9002,
        name="repo-two",
        full_name="ada/repo-two",
        installation_id=inst_ada.id,
        removed_at=None,
        created_at=INSIDE,
        settings={
            "assigned_provider": "groq",
            "assigned_model": "llama-3.3-70b",
            "assigned_key_id": str(k_ada_groq.id),
        },
    )
    r_three = Repository(
        github_id=9003,
        name="repo-three",
        full_name="grace/repo-three",
        installation_id=inst_grace.id,
        removed_at=None,
        created_at=INSIDE,
        settings={},
    )
    r_four = Repository(
        github_id=9004,
        name="repo-four",
        full_name="grace/repo-four",
        installation_id=inst_grace.id,
        removed_at=None,
        created_at=INSIDE,
        settings={
            "assigned_provider": "openai",
            "assigned_model": "gpt-4o",
            "assigned_key_id": str(k_ada_openai_invalid.id),
        },
    )
    r_five = Repository(
        github_id=9005,
        name="repo-five",
        full_name="grace/repo-five",
        installation_id=inst_grace.id,
        removed_at=INSIDE,
        created_at=INSIDE,
        settings={},
    )
    test_db.add_all([r_one, r_two, r_three, r_four, r_five])
    await test_db.commit()

    prs = []
    for index, (repo, number) in enumerate(
        [
            (r_one, 11),
            (r_two, 12),
            (r_three, 13),
            (r_four, 14),
            (r_one, 15),
        ],
        start=1,
    ):
        prs.append(
            PullRequest(
                repo_id=repo.id,
                pr_number=number,
                title=f"PR {number}",
                author="ada",
                head_sha="a" * 40,
                base_branch="main",
                head_branch=f"feature-{number}",
                status="open",
            )
        )
    test_db.add_all(prs)
    await test_db.commit()

    statuses = ["completed", "failed", "completed", "completed", "pending"]
    reviews = [
        Review(
            pr_id=pr.id,
            status=status,
            created_at=INSIDE + timedelta(minutes=index),
            completed_at=INSIDE if status == "completed" else None,
        )
        for index, (pr, status) in enumerate(zip(prs, statuses, strict=True))
    ]
    test_db.add_all(reviews)
    await test_db.commit()

    executions = [
        ReviewExecution(
            review_id=reviews[0].id,
            execution_number=1,
            trigger="webhook",
            status="completed",
            provider="openai",
            model="gpt-4o",
            started_at=INSIDE,
            completed_at=INSIDE + timedelta(seconds=1),
            duration_ms=100,
        ),
        ReviewExecution(
            review_id=reviews[1].id,
            execution_number=1,
            trigger="webhook",
            status="failed",
            provider="groq",
            model="llama-3.3-70b",
            started_at=INSIDE,
            error_message="Rate limit exceeded (429) for organization",
        ),
        ReviewExecution(
            review_id=reviews[1].id,
            execution_number=2,
            trigger="retry",
            status="failed",
            provider="groq",
            model="llama-3.3-70b",
            started_at=INSIDE + timedelta(minutes=1),
            error_message="Rate limit exceeded (429) for organization",
        ),
        ReviewExecution(
            review_id=reviews[2].id,
            execution_number=1,
            trigger="webhook",
            status="completed",
            provider="openai",
            model="gpt-4o",
            started_at=INSIDE,
            completed_at=INSIDE + timedelta(seconds=2),
            duration_ms=200,
        ),
        ReviewExecution(
            review_id=reviews[3].id,
            execution_number=1,
            trigger="webhook",
            status="failed",
            provider="openai",
            model="gpt-4o-mini",
            started_at=INSIDE,
            error_message="Connection timeout after 30s",
        ),
        ReviewExecution(
            review_id=reviews[3].id,
            execution_number=2,
            trigger="retry",
            status="completed",
            provider="openai",
            model="gpt-4o-mini",
            started_at=INSIDE + timedelta(minutes=2),
            completed_at=INSIDE + timedelta(minutes=3),
            duration_ms=300,
        ),
        ReviewExecution(
            review_id=reviews[4].id,
            execution_number=1,
            trigger="webhook",
            status="running",
            provider=None,
            model=None,
            started_at=INSIDE,
        ),
    ]
    test_db.add_all(executions)

    test_db.add_all(
        [
            ProviderHealth(
                provider="openai",
                status="degraded",
                success_rate=0.90,
                created_at=INSIDE - timedelta(days=1),
            ),
            ProviderHealth(
                provider="openai",
                status="healthy",
                success_rate=0.99,
                created_at=INSIDE,
            ),
            ProviderHealth(
                provider="groq",
                status="down",
                circuit_state="open",
                success_rate=0.10,
                last_error="503 Service Unavailable",
                last_error_at=INSIDE,
                created_at=INSIDE,
            ),
        ]
    )
    test_db.add(FeatureFlag(key="model_lab", status="enabled"))
    await test_db.commit()

    return {
        "users": {"ada": ada, "grace": grace, "alan": alan, "early": early},
        "repos": {
            "one": r_one,
            "two": r_two,
            "three": r_three,
            "four": r_four,
            "five": r_five,
        },
        "reviews": reviews,
        "keys": {
            "ada_openai": k_ada_openai,
            "ada_groq": k_ada_groq,
            "ada_invalid": k_ada_openai_invalid,
        },
    }


async def _overview(test_db, start=WINDOW_START, end=WINDOW_END) -> dict:
    return await admin_stats.overview(
        test_db, period_key="custom", start=start, end=end
    )


# ---------------------------------------------------------------------------
# B11 — every widget equals direct SQL on the seeded fixture
# ---------------------------------------------------------------------------


async def test_b11_overview_widgets_match_seed(test_db, seeded):
    data = await _overview(test_db)

    assert data["users_total"] == 4
    assert data["users_new_in_period"] == 3

    assert data["credentials_total"] == 4
    by_provider = {row["provider"]: row for row in data["credentials_by_provider"]}
    assert by_provider["openai"] == {
        "provider": "openai",
        "total": 3,
        "valid": 2,
        "invalid": 1,
        "enabled": 3,
        "disabled": 0,
    }
    assert by_provider["groq"]["total"] == 1
    assert by_provider["groq"]["disabled"] == 1

    assert data["repos_connected"] == 4

    assert data["reviews_total"] == 5
    assert data["reviews_in_period"] == 5
    assert data["reviews_by_status"] == {
        "completed": 3,
        "failed": 1,
        "pending": 1,
    }
    assert data["retries_in_period"] == 2

    pm = {
        (row["provider"], row["model"]): row["count"]
        for row in data["reviews_by_provider_model"]
    }
    assert pm == {
        ("openai", "gpt-4o"): 2,
        ("groq", "llama-3.3-70b"): 1,
        ("openai", "gpt-4o-mini"): 1,
        (None, None): 1,
    }

    assert data["duration_p50_ms"]["value"] == 200.0
    assert data["duration_p95_ms"]["value"] == 290.0

    assert data["failure_rate"]["value"] == pytest.approx(0.2)
    assert data["failure_rate"]["sample_size"] == 5
    assert data["failure_categories"] == [{"category": "rate limit", "count": 1}]

    health = {row["provider"]: row for row in data["provider_health"]}
    assert health["openai"]["status"] == "healthy"
    assert health["openai"]["success_rate"] == pytest.approx(0.99)
    assert health["groq"]["circuit_state"] == "open"
    assert health["groq"]["last_error"] == "503 Service Unavailable"

    assert data["features"] == {"model_lab": "enabled"}
    assert data["maintenance"]["enabled"] is False


# ---------------------------------------------------------------------------
# B13 — unrecorded fields are marked, never fabricated
# ---------------------------------------------------------------------------


async def test_b13_unrecorded_metrics_marked_never_zero(test_db, seeded):
    data = await _overview(test_db)

    assert data["signed_in_users"]["available"] is False
    assert data["signed_in_users"]["value"] is None
    assert "not yet recorded" in data["signed_in_users"]["reason"]
    assert data["last_login_at"]["available"] is False
    for key in ("24h", "7d", "30d"):
        assert data["active_users"][key]["available"] is False
        assert data["active_users"][key]["value"] is None
        assert "not yet recorded" in data["active_users"][key]["reason"]

    assert data["token_usage"]["available"] is False
    assert data["token_usage"]["value"] is None
    assert "USAGE_ANALYTICS_ENABLED" in data["token_usage"]["reason"]
    assert data["cost_totals"]["available"] is False

    empty = await _overview(
        test_db,
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 2, tzinfo=UTC),
    )
    assert empty["duration_p50_ms"]["value"] is None
    assert empty["duration_p95_ms"]["value"] is None
    assert empty["duration_p50_ms"]["available"] is True
    assert empty["failure_rate"]["value"] is None
    assert empty["failure_rate"]["sample_size"] == 0


# ---------------------------------------------------------------------------
# B12 — half-open window boundaries, UTC
# ---------------------------------------------------------------------------


async def test_b12_period_boundaries_half_open(test_db, seeded):
    at_start = Review(
        pr_id=seeded["reviews"][0].pr_id,
        status="completed",
        created_at=WINDOW_START,
    )
    at_end = Review(
        pr_id=seeded["reviews"][0].pr_id,
        status="completed",
        created_at=WINDOW_END,
    )
    test_db.add_all([at_start, at_end])
    await test_db.commit()

    data = await _overview(test_db)
    assert data["reviews_in_period"] == 6

    page = await admin_stats.list_reviews(
        test_db,
        user=None,
        repo=None,
        provider=None,
        model=None,
        status=None,
        error=None,
        period="custom",
        start=WINDOW_START.isoformat(),
        end=WINDOW_END.isoformat(),
        limit=100,
        offset=0,
    )
    ids = {item["id"] for item in page["items"]}
    assert at_start.id in ids
    assert at_end.id not in ids


# ---------------------------------------------------------------------------
# B30 — pagination/filter abuse
# ---------------------------------------------------------------------------


def test_b30_pagination_abuse_rejected(admin_client):
    cases = [
        (f"{OVERVIEW_URL}?period=13d", 400),
        (f"{OVERVIEW_URL}?period=custom", 400),
          (
            (
                f"{OVERVIEW_URL}?period=custom&start=2026-10-16T00:00:00Z"
                "&end=2026-10-01T00:00:00Z"
            ),
            400,
          ),
        ("/api/v1/admin/users?limit=10000", 400),
        ("/api/v1/admin/users?limit=0", 400),
        ("/api/v1/admin/users?offset=-1", 400),
        ("/api/v1/admin/users?sort=hax", 400),
        ("/api/v1/admin/users?status=bogus", 400),
        ("/api/v1/admin/repositories?limit=101", 400),
        ("/api/v1/admin/repositories?mapping=weird", 400),
        ("/api/v1/admin/reviews?offset=-5", 400),
    ]
    for url, expected in cases:
        response = admin_client.get(url)
        assert response.status_code == expected, (url, response.text)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


async def test_users_list_counts_and_filters(test_db, seeded):
    data = await admin_stats.list_users(
        test_db, q=None, status=None, sort="created", limit=10, offset=0
    )
    assert data["total"] == 4
    by_email = {item["email"]: item for item in data["items"]}

    ada = by_email["ada@example.com"]
    assert ada["repo_count"] == 2
    assert ada["credential_count"] == 3
    assert ada["review_count"] == 3
    assert ada["status"] == "active"
    assert ada["last_login_at"] is None

    grace = by_email["grace@example.com"]
    assert grace["repo_count"] == 2  # includes the removed repo
    assert grace["credential_count"] == 1
    assert grace["review_count"] == 2

    disabled = await admin_stats.list_users(
        test_db, q=None, status="disabled", sort="created", limit=10, offset=0
    )
    assert [item["email"] for item in disabled["items"]] == ["alan@example.com"]

    search = await admin_stats.list_users(
        test_db, q="grace", status=None, sort="created", limit=10, offset=0
    )
    assert [item["email"] for item in search["items"]] == ["grace@example.com"]

    literal_wildcard = await admin_stats.list_users(
        test_db, q="grace%", status=None, sort="created", limit=10, offset=0
    )
    assert literal_wildcard["total"] == 0, "SQL wildcards in q must be literal"


async def test_users_sort_by_reviews(test_db, seeded):
    data = await admin_stats.list_users(
        test_db, q=None, status=None, sort="reviews", limit=2, offset=0
    )
    assert data["items"][0]["review_count"] >= data["items"][1]["review_count"]
    assert len(data["items"]) == 2


async def test_user_detail_shape_and_no_secrets(test_db, seeded):
    ada = seeded["users"]["ada"]
    detail = await admin_stats.user_detail(
        test_db, ada.id, reviews_limit=20, reviews_offset=0
    )
    assert detail["profile"]["email"] == "ada@example.com"
    assert len(detail["repositories"]) == 2
    assert len(detail["credentials"]) == 3
    assert detail["reviews"]["total"] == 3
    assert detail["reviews"]["status_counts"] == {
        "completed": 1,
        "failed": 1,
        "pending": 1,
    }

    serialized = str(detail)
    assert "encrypted-blob" not in serialized
    assert "encrypted_key" not in serialized
    assert "password_hash" not in serialized

    openai_key = next(
        c for c in detail["credentials"] if c["label"] == "primary"
    )
    assert openai_key["is_valid"] is True
    assert openai_key["is_enabled"] is True


async def test_user_detail_missing_returns_none(test_db):
    assert (
        await admin_stats.user_detail(
            test_db, uuid.uuid4(), reviews_limit=20, reviews_offset=0
        )
        is None
    )


# ---------------------------------------------------------------------------
# Repositories — mapping health
# ---------------------------------------------------------------------------


async def test_repository_mapping_health_states(test_db, seeded):
    data = await admin_stats.list_repositories(
        test_db, user=None, provider=None, mapping=None, limit=100, offset=0
    )
    health = {
        item["full_name"]: item["mapping_health"] for item in data["items"]
    }
    assert health["ada/repo-one"] == "ok"
    assert health["ada/repo-two"] == "stale"  # provider unavailable
    assert health["grace/repo-four"] == "stale"  # assigned key invalid
    assert health["grace/repo-three"] == "missing"
    assert health["grace/repo-five"] == "missing"

    ok_only = await admin_stats.list_repositories(
        test_db, user=None, provider=None, mapping="ok", limit=100, offset=0
    )
    assert [item["full_name"] for item in ok_only["items"]] == ["ada/repo-one"]
    assert ok_only["total"] == 1

    stale_only = await admin_stats.list_repositories(
        test_db, user=None, provider=None, mapping="stale", limit=100, offset=0
    )
    assert {item["full_name"] for item in stale_only["items"]} == {
        "ada/repo-two",
        "grace/repo-four",
    }
    assert stale_only["total"] == 2


async def test_repository_override_marks_stale(test_db, seeded):
    repo = seeded["repos"]["one"]
    repo.settings = {
        "assigned_provider": "openai",
        "assigned_model": "gpt-4o-mini",
        "assigned_key_id": str(seeded["keys"]["ada_openai"].id),
    }
    test_db.add(repo)
    await test_db.commit()

    data = await admin_stats.list_repositories(
        test_db, user="ada@example.com", provider=None, mapping=None, limit=100, offset=0
    )
    by_name = {item["full_name"]: item for item in data["items"]}
    assert by_name["ada/repo-one"]["mapping_health"] == "stale"


async def test_repository_filters_and_counts(test_db, seeded):
    data = await admin_stats.list_repositories(
        test_db,
        user="ada@example.com",
        provider="openai",
        mapping=None,
        limit=100,
        offset=0,
    )
    assert data["total"] == 1
    item = data["items"][0]
    assert item["full_name"] == "ada/repo-one"
    assert item["owner_github_username"] == "ada"
    assert item["review_count"] == 2
    assert item["last_review_at"] is not None
    assert item["recent_failures_7d"] >= 0


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------


async def test_reviews_configured_vs_actual_and_unrecorded(test_db, seeded):
    data = await admin_stats.list_reviews(
        test_db,
        user=None,
        repo=None,
        provider=None,
        model=None,
        status=None,
        error=None,
        period=None,
        start=None,
        end=None,
        limit=100,
        offset=0,
    )
    assert data["total"] == 5
    by_id = {item["id"]: item for item in data["items"]}

    # Review 4 configured openai/gpt-4o but actually ran gpt-4o-mini (fallback).
    review_four = by_id[seeded["reviews"][3].id]
    assert review_four["configured_provider"] == "openai"
    assert review_four["configured_model"] == "gpt-4o"
    assert review_four["provider"] == "openai"
    assert review_four["model"] == "gpt-4o-mini"

    # Review 5 has an execution with NULL provider/model -> unrecorded (null).
    review_five = by_id[seeded["reviews"][4].id]
    assert review_five["provider"] is None
    assert review_five["model"] is None
    assert review_five["execution_status"] == "running"


async def test_reviews_filters(test_db, seeded):
    by_provider = await admin_stats.list_reviews(
        test_db,
        user=None,
        repo=None,
        provider="groq",
        model=None,
        status=None,
        error=None,
        period=None,
        start=None,
        end=None,
        limit=100,
        offset=0,
    )
    assert by_provider["total"] == 1
    assert by_provider["items"][0]["id"] == seeded["reviews"][1].id

    by_error = await admin_stats.list_reviews(
        test_db,
        user=None,
        repo=None,
        provider=None,
        model=None,
        status=None,
        error="timeout",
        period=None,
        start=None,
        end=None,
        limit=100,
        offset=0,
    )
    # "timeout" happened on the retried execution; the latest one succeeded.
    assert by_error["total"] == 0

    sanitized = await admin_stats.list_reviews(
        test_db,
        user=None,
        repo=None,
        provider=None,
        model=None,
        status="failed",
        error=None,
        period="custom",
        start=WINDOW_START.isoformat(),
        end=WINDOW_END.isoformat(),
        limit=100,
        offset=0,
    )
    assert sanitized["total"] == 1
    assert sanitized["items"][0]["error"] == "Rate limit exceeded (429) for organization"


# ---------------------------------------------------------------------------
# Bounded queries + server-side pagination (acceptance: 10k rows)
# ---------------------------------------------------------------------------


async def test_lists_stay_bounded_on_10k_users(test_engine, test_db):
    await test_db.execute(
        User.__table__.insert(),
        [
            {
                "id": uuid.uuid4(),
                "name": f"Bulk User {index}",
                "email": f"bulk{index}@example.com",
                "role": "user",
                "is_verified": True,
                "status": "active",
                "token_version": 0,
                "settings": {},
                "created_at": datetime(2026, 10, 1, tzinfo=UTC),
                "updated_at": datetime(2026, 10, 1, tzinfo=UTC),
            }
            for index in range(10_000)
        ],
    )
    await test_db.commit()

    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", _record)
    try:
        page = await admin_stats.list_users(
            test_db, q=None, status=None, sort="created", limit=50, offset=0
        )
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", _record)

    assert page["total"] == 10_000
    assert len(page["items"]) == 50
    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) <= 3, f"unexpected query fan-out: {selects}"


# ---------------------------------------------------------------------------
# S6 subset — response scanner over the new endpoints
# ---------------------------------------------------------------------------

_SECRET_RE = re.compile(
    r"(encrypted_key|encrypted-blob|password_hash|token_hash|\bsk-[A-Za-z0-9]{8,})"
)


def _iso_url(dt: datetime) -> str:
    """URL-safe ISO-8601 (a literal '+' would decode as a space)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_no_secret_material_in_any_admin_read_response(
    admin_client, seeded
):
    urls = [
        (
            f"{OVERVIEW_URL}?period=custom"
            f"&start={_iso_url(WINDOW_START)}&end={_iso_url(WINDOW_END)}"
        ),
        "/api/v1/admin/users",
        f"/api/v1/admin/users/{seeded['users']['ada'].id}",
        "/api/v1/admin/repositories",
        "/api/v1/admin/reviews",
    ]
    for url in urls:
        response = admin_client.get(url)
        assert response.status_code == 200, (url, response.text)
        assert not _SECRET_RE.search(response.text), url


def test_admin_read_endpoints_respond(admin_client, seeded):
    response = admin_client.get(
        f"{OVERVIEW_URL}?period=custom"
        f"&start={_iso_url(WINDOW_START)}&end={_iso_url(WINDOW_END)}"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["users_total"] == 4
    assert body["signed_in_users"]["available"] is False

    users = admin_client.get("/api/v1/admin/users?limit=2").json()
    assert users["total"] == 4
    assert len(users["items"]) == 2

    detail = admin_client.get(
        f"/api/v1/admin/users/{seeded['users']['ada'].id}"
    )
    assert detail.status_code == 200
    assert detail.json()["profile"]["email"] == "ada@example.com"

    assert (
        admin_client.get(f"/api/v1/admin/users/{uuid.uuid4()}").status_code
        == 404
    )
    assert admin_client.get("/api/v1/admin/repositories?mapping=ok").json()[
        "total"
    ] == 1
    assert admin_client.get("/api/v1/admin/reviews?provider=groq").json()[
        "total"
    ] == 1
