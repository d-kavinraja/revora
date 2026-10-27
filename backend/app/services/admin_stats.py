"""Read-only admin analytics queries (phase 2).

Set-based aggregates only: constant-query overview widgets, LIMIT-bounded
list pages with server-side pagination (``limit <= 100``), no per-row IO and
no provider API calls. Error strings are sanitized before they are returned
(the ``api_keys.sanitize_error_message`` pattern). Key material is never
selected.

Metric integrity (plan §7, binding): every value comes from stored rows.
Unrecorded metrics return ``{"available": false, "reason": ...}`` — never a
fabricated ``0``.
"""

import uuid as uuid_lib
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import String, and_, case, cast, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.api_keys import sanitize_error_message
from app.core.config import settings as app_config
from app.models.api_key import ApiKey
from app.models.audit import AuditLog
from app.models.execution import ReviewExecution
from app.models.github import Installation, PullRequest, Repository
from app.models.health import ApiKeyHealth, ProviderHealth
from app.models.platform import FeatureFlag, ModelOverride, PlatformSetting
from app.models.provider import ProviderRegistry
from app.models.review import Review
from app.models.token_usage import LlmTokenUsage
from app.models.user import User

MAX_PAGE = 100
DEFAULT_PAGE = 50

USER_STATUSES = ("active", "disabled")
USER_SORTS = ("created", "last_login", "reviews")
MAPPING_STATES = ("ok", "stale", "missing")

PERIOD_DELTAS = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}

LOGIN_NOT_RECORDED = "login tracking not yet recorded"
ACTIVITY_NOT_RECORDED = "activity tracking not yet recorded"
USAGE_DISABLED_REASON = (
    "usage analytics disabled (USAGE_ANALYTICS_ENABLED=False)"
)


class InvalidQuery(ValueError):
    """Invalid query parameter -> HTTP 400 at the endpoint boundary."""


async def get_user(db: AsyncSession, user_id: uuid_lib.UUID) -> User | None:
    """Single-row user lookup for admin mutations (phase 3)."""
    return (
        await db.execute(select(User).where(User.id == user_id))
    ).scalars().first()


# ---------------------------------------------------------------------------
# Parameter validation
# ---------------------------------------------------------------------------


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip())
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def resolve_period(
    period: str,
    start: str | None,
    end: str | None,
    *,
    now: datetime | None = None,
) -> tuple[str, datetime, datetime]:
    """Resolve a period key to a half-open UTC window ``[start, end)``."""
    now = now or datetime.now(UTC)
    if period == "custom":
        if not start or not end:
            raise InvalidQuery("custom period requires both start and end")
        try:
            start_dt = _parse_dt(start)
            end_dt = _parse_dt(end)
        except ValueError as exc:
            raise InvalidQuery("start/end must be ISO-8601 datetimes") from exc
        if start_dt >= end_dt:
            raise InvalidQuery("start must be before end")
        return period, start_dt, end_dt

    delta = PERIOD_DELTAS.get(period)
    if delta is None:
        raise InvalidQuery("period must be one of 24h, 7d, 30d, custom")
    return period, now - delta, now


def validate_pagination(limit: int, offset: int) -> tuple[int, int]:
    if limit < 1 or limit > MAX_PAGE:
        raise InvalidQuery(f"limit must be between 1 and {MAX_PAGE}")
    if offset < 0:
        raise InvalidQuery("offset must be >= 0")
    return limit, offset


def _like(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    return f"%{escaped}%"


def _percentile(values: list[int], fraction: float) -> float | None:
    """Linear-interpolated percentile (matches ``percentile_cont``)."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = fraction * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return float(ordered[lower]) * (1 - weight) + float(ordered[upper]) * weight


# ---------------------------------------------------------------------------
# Derived repository mapping health (§7.3)
# ---------------------------------------------------------------------------


def _mapping_parts():
    """JSON mapping columns plus the derived ``ok|stale|missing`` expression.

    Staleness sources (all SQL-visible): provider missing/disabled/not
    available, model override not available, assigned key missing/disabled/
    invalid. Key id comparison normalizes both sides to dash-less hex for
    cross-dialect parity (Postgres uuid text vs SQLite 32-char storage).
    """
    provider = Repository.settings["assigned_provider"].as_string()
    model = Repository.settings["assigned_model"].as_string()
    key_id = Repository.settings["assigned_key_id"].as_string()
    health = case(
        (or_(provider.is_(None), model.is_(None)), "missing"),
        (
            or_(
                ProviderRegistry.id.is_(None),
                ProviderRegistry.is_enabled.is_(False),
                ProviderRegistry.status != "available",
            ),
            "stale",
        ),
        (
            and_(
                ModelOverride.id.is_not(None),
                ModelOverride.status != "available",
            ),
            "stale",
        ),
        (
            and_(
                key_id.is_not(None),
                or_(
                    ApiKey.id.is_(None),
                    ApiKey.is_enabled.is_(False),
                    ApiKey.is_valid.is_(False),
                ),
            ),
            "stale",
        ),
        else_="ok",
    )
    return provider, model, key_id, health


def _mapping_joins(stmt):
    """Outer-joins registry/override/assigned-key for the mapping expression.

    Requires ``User`` to be present in the statement's FROM clause.
    """
    provider, model, key_id, _ = _mapping_parts()
    key_norm = func.replace(cast(ApiKey.id, String), "-", "")
    return (
        stmt.outerjoin(ProviderRegistry, ProviderRegistry.slug == provider)
        .outerjoin(
            ModelOverride,
            and_(
                ModelOverride.provider_slug == provider,
                ModelOverride.model_id == model,
            ),
        )
        .outerjoin(
            ApiKey,
            and_(
                ApiKey.user_id == User.id,
                key_norm == func.replace(key_id, "-", ""),
            ),
        )
    )


# ---------------------------------------------------------------------------
# Overview (§7.1)
# ---------------------------------------------------------------------------


def _latest_execution_subquery():
    return select(
        ReviewExecution.review_id,
        ReviewExecution.provider,
        ReviewExecution.model,
        ReviewExecution.status,
        ReviewExecution.error_message,
        func.row_number()
        .over(
            partition_by=ReviewExecution.review_id,
            order_by=ReviewExecution.execution_number.desc(),
        )
        .label("rn"),
    ).subquery()


_ERROR_CATEGORY_RULES = (
    ("rate limit", ("rate limit", "too many requests", "429")),
    ("quota/credits", ("quota", "credit", "billing", "insufficient")),
    (
        "authentication",
        ("unauthorized", "authentication", "invalid api key", "401"),
    ),
    ("timeout", ("timeout", "timed out", "deadline")),
    ("provider unavailable", ("unavailable", "overloaded", "503", "502")),
)


def _error_category(message: str) -> str:
    lowered = (message or "").lower()
    for label, needles in _ERROR_CATEGORY_RULES:
        if any(needle in lowered for needle in needles):
            return label
    return "other"


async def overview(
    db: AsyncSession, *, period_key: str, start: datetime, end: datetime
) -> dict[str, Any]:
    users_total, users_new = (
        await db.execute(
            select(
                func.count(User.id),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    User.created_at >= start,
                                    User.created_at < end,
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
            )
        )
    ).one()

    credentials_total = (
        await db.execute(select(func.count(ApiKey.id)))
    ).scalar_one()
    credential_rows = (
        await db.execute(
            select(
                ApiKey.provider,
                ApiKey.is_valid,
                ApiKey.is_enabled,
                func.count(ApiKey.id),
            ).group_by(ApiKey.provider, ApiKey.is_valid, ApiKey.is_enabled)
        )
    ).all()
    credentials_by_provider: dict[str, dict[str, Any]] = {}
    for provider_slug, is_valid, is_enabled, count in credential_rows:
        entry = credentials_by_provider.setdefault(
            provider_slug,
            {
                "provider": provider_slug,
                "total": 0,
                "valid": 0,
                "invalid": 0,
                "enabled": 0,
                "disabled": 0,
            },
        )
        entry["total"] += count
        entry["valid" if is_valid else "invalid"] += count
        entry["enabled" if is_enabled else "disabled"] += count

    repos_connected = (
        await db.execute(
            select(func.count(Repository.id)).where(
                Repository.removed_at.is_(None)
            )
        )
    ).scalar_one()

    reviews_total = (
        await db.execute(select(func.count(Review.id)))
    ).scalar_one()
    windowed = and_(Review.created_at >= start, Review.created_at < end)
    review_status_rows = (
        await db.execute(
            select(Review.status, func.count(Review.id))
            .where(windowed)
            .group_by(Review.status)
        )
    ).all()
    reviews_by_status = {status: count for status, count in review_status_rows}
    reviews_in_period = sum(reviews_by_status.values())

    retries_in_period = (
        await db.execute(
            select(
                func.coalesce(
                    func.sum(ReviewExecution.execution_number - 1), 0
                )
            )
            .join(Review, Review.id == ReviewExecution.review_id)
            .where(windowed)
        )
    ).scalar_one()

    latest = _latest_execution_subquery()
    provider_model_rows = (
        await db.execute(
            select(latest.c.provider, latest.c.model, func.count())
            .join(Review, Review.id == latest.c.review_id)
            .where(latest.c.rn == 1, windowed)
            .group_by(latest.c.provider, latest.c.model)
            .order_by(func.count().desc())
        )
    ).all()
    reviews_by_provider_model = [
        {"provider": provider, "model": model, "count": count}
        for provider, model, count in provider_model_rows
    ]

    duration_filter = and_(
        ReviewExecution.completed_at.is_not(None),
        ReviewExecution.duration_ms.is_not(None),
        ReviewExecution.started_at >= start,
        ReviewExecution.started_at < end,
    )
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        p50, p95 = (
            await db.execute(
                select(
                    func.percentile_cont(0.5).within_group(
                        ReviewExecution.duration_ms
                    ),
                    func.percentile_cont(0.95).within_group(
                        ReviewExecution.duration_ms
                    ),
                ).where(duration_filter)
            )
        ).one()
    else:
        duration_values = (
            (
                await db.execute(
                    select(ReviewExecution.duration_ms).where(
                        duration_filter
                    )
                )
            )
            .scalars()
            .all()
        )
        p50 = _percentile(list(duration_values), 0.5)
        p95 = _percentile(list(duration_values), 0.95)

    latest_total, latest_failed = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(
                    func.sum(case((latest.c.status == "failed", 1), else_=0)),
                    0,
                ),
            )
            .join(Review, Review.id == latest.c.review_id)
            .where(latest.c.rn == 1, windowed)
        )
    ).one()
    failure_rate = (
        (latest_failed / latest_total) if latest_total else None
    )

    error_rows = (
        (
            await db.execute(
                select(latest.c.error_message)
                .join(Review, Review.id == latest.c.review_id)
                .where(
                    latest.c.rn == 1,
                    latest.c.status == "failed",
                    latest.c.error_message.is_not(None),
                    windowed,
                )
                .limit(500)
            )
        )
        .scalars()
        .all()
    )
    category_counts: dict[str, int] = {}
    for raw_message in error_rows:
        category = _error_category(sanitize_error_message(raw_message))
        category_counts[category] = category_counts.get(category, 0) + 1
    failure_categories = [
        {"category": category, "count": count}
        for category, count in sorted(
            category_counts.items(), key=lambda item: (-item[1], item[0])
        )[:5]
    ]

    health_ranked = select(
        ProviderHealth.provider,
        ProviderHealth.status,
        ProviderHealth.success_rate,
        ProviderHealth.circuit_state,
        ProviderHealth.last_error,
        ProviderHealth.last_error_at,
        ProviderHealth.created_at,
        func.row_number()
        .over(
            partition_by=ProviderHealth.provider,
            order_by=ProviderHealth.created_at.desc(),
        )
        .label("rn"),
    ).subquery()
    health_rows = (
        await db.execute(
            select(health_ranked)
            .where(health_ranked.c.rn == 1)
            .order_by(health_ranked.c.provider)
        )
    ).all()
    provider_health = [
        {
            "provider": row.provider,
            "status": row.status,
            "success_rate": row.success_rate,
            "circuit_state": row.circuit_state,
            "last_error": (
                sanitize_error_message(row.last_error)
                if row.last_error
                else None
            ),
            "last_error_at": row.last_error_at,
            "snapshot_at": row.created_at,
        }
        for row in health_rows
    ]

    maintenance_value = (
        await db.execute(
            select(PlatformSetting.value).where(
                PlatformSetting.key == "maintenance"
            )
        )
    ).scalar_one_or_none()
    maintenance: dict[str, Any] = {
        "enabled": False,
        "title": None,
        "message": None,
        "expected_return_at": None,
    }
    if isinstance(maintenance_value, dict):
        maintenance["enabled"] = bool(maintenance_value.get("enabled", False))
        maintenance["title"] = maintenance_value.get("title")
        maintenance["message"] = maintenance_value.get("message")
        maintenance["expected_return_at"] = maintenance_value.get(
            "expected_return_at"
        )

    feature_rows = (
        await db.execute(select(FeatureFlag.key, FeatureFlag.status))
    ).all()
    features = {key: status for key, status in feature_rows}

    if app_config.USAGE_ANALYTICS_ENABLED:
        tokens_total, cost_total = (
            await db.execute(
                select(
                    func.coalesce(func.sum(LlmTokenUsage.total_tokens), 0),
                    func.coalesce(func.sum(LlmTokenUsage.total_cost_usd), 0.0),
                ).where(
                    LlmTokenUsage.created_at >= start,
                    LlmTokenUsage.created_at < end,
                )
            )
        ).one()
        token_usage = {"available": True, "value": int(tokens_total), "reason": None}
        cost_totals = {
            "available": True,
            "value": float(cost_total),
            "reason": None,
        }
    else:
        token_usage = {
            "available": False,
            "value": None,
            "reason": USAGE_DISABLED_REASON,
        }
        cost_totals = {
            "available": False,
            "value": None,
            "reason": USAGE_DISABLED_REASON,
        }

    # Auth + activity metrics (phase 7, §3.4): counts come from stored
    # timestamps, never fabricated. Availability is gated on recorded data
    # (§13): historical rows stay "Not recorded" until at least one user has
    # either logged in or been active, so the B13 contract holds.
    logins_in_period = int(
        (
            await db.execute(
                select(func.count(User.id)).where(
                    User.last_login_at.is_not(None),
                    User.last_login_at >= start,
                    User.last_login_at < end,
                )
            )
        ).scalar_one()
    )
    logged_in_count = int(
        (
            await db.execute(
                select(func.count(User.id)).where(
                    User.last_login_at.is_not(None)
                )
            )
        ).scalar_one()
    )
    login_max = (await db.execute(select(func.max(User.last_login_at)))).scalar_one()
    if logged_in_count > 0:
        signed_in_users = {
            "available": True,
            "value": logins_in_period,
            "reason": None,
        }
        last_login_at = {
            "available": True,
            "value": login_max.isoformat() if login_max else None,
            "reason": None,
        }
    else:
        signed_in_users = {
            "available": False,
            "value": None,
            "reason": LOGIN_NOT_RECORDED,
        }
        last_login_at = {
            "available": False,
            "value": None,
            "reason": LOGIN_NOT_RECORDED,
        }

    # Active-user counts by window (users with `last_active_at` inside each
    # [cutoff, end) band). Global presence governs availability; each band
    # reports its own real count.
    active_users: dict[str, dict[str, Any]] = {}
    if (
        int(
            (
                await db.execute(
                    select(func.count(User.id)).where(
                        User.last_active_at.is_not(None)
                    )
                )
            ).scalar_one()
        )
        > 0
    ):
        for key, delta in PERIOD_DELTAS.items():
            window_cutoff = end - delta
            count = int(
                (
                    await db.execute(
                        select(func.count(User.id)).where(
                            User.last_active_at.is_not(None),
                            User.last_active_at >= window_cutoff,
                            User.last_active_at < end,
                        )
                    )
                ).scalar_one()
            )
            active_users[key] = {
                "available": True,
                "value": count,
                "reason": None,
            }
    else:
        active_users = {
            key: {
                "available": False,
                "value": None,
                "reason": ACTIVITY_NOT_RECORDED,
            }
            for key in ("24h", "7d", "30d")
        }

    return {
        "period": {"key": period_key, "start": start, "end": end},
        "users_total": users_total,
        "users_new_in_period": int(users_new),
        "signed_in_users": signed_in_users,
        "last_login_at": last_login_at,
        "active_users": active_users,
        "credentials_total": credentials_total,
        "credentials_by_provider": sorted(
            credentials_by_provider.values(),
            key=lambda item: (-item["total"], item["provider"]),
        ),
        "repos_connected": repos_connected,
        "reviews_total": reviews_total,
        "reviews_in_period": reviews_in_period,
        "reviews_by_status": reviews_by_status,
        "reviews_by_provider_model": reviews_by_provider_model,
        "retries_in_period": int(retries_in_period),
        "duration_p50_ms": {"available": True, "value": p50, "reason": None},
        "duration_p95_ms": {"available": True, "value": p95, "reason": None},
        "failure_rate": {
            "available": True,
            "value": failure_rate,
            "reason": None,
            "sample_size": int(latest_total),
        },
        "failure_categories": failure_categories,
        "provider_health": provider_health,
        "maintenance": maintenance,
        "features": features,
        "token_usage": token_usage,
        "cost_totals": cost_totals,
    }


# ---------------------------------------------------------------------------
# Audit log viewer (§16)
# ---------------------------------------------------------------------------


async def list_audit(
    db: AsyncSession,
    *,
    action: str | None = None,
    actor: str | None = None,
    entity_type: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = DEFAULT_PAGE,
    offset: int = 0,
) -> dict[str, Any]:
    """Paginated audit-log read (§16).

    `action`/`entity_type` match exactly, `actor` is a substring match on
    `actor_id`; an omitted window means "all history" (no auto-purge, so
    older operational records stay reachable). Newest first.
    """
    filters = []
    if action:
        filters.append(AuditLog.action == action.strip())
    if actor:
        filters.append(
            AuditLog.actor_id.ilike(_like(actor.strip()), escape="\\")
        )
    if entity_type:
        filters.append(AuditLog.entity_type == entity_type.strip())
    if start is not None:
        filters.append(AuditLog.created_at >= start)
    if end is not None:
        filters.append(AuditLog.created_at < end)

    total = (
        await db.execute(select(func.count(AuditLog.id)).where(*filters))
    ).scalar_one()
    rows = (
        await db.execute(
            select(
                AuditLog.id,
                AuditLog.actor_id,
                AuditLog.actor_type,
                AuditLog.action,
                AuditLog.entity_type,
                AuditLog.entity_id,
                AuditLog.details,
                AuditLog.ip_address,
                AuditLog.user_agent,
                AuditLog.created_at,
            )
            .where(*filters)
            .order_by(desc(AuditLog.created_at), desc(AuditLog.id))
            .limit(limit)
            .offset(offset)
        )
    ).all()
    items = []
    for row in rows:
        details = row.details or {}
        items.append(
            {
                "id": row.id,
                "actor_id": row.actor_id,
                "actor_type": row.actor_type,
                "action": row.action,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "outcome": details.get("outcome"),
                "details": details,
                "ip_address": row.ip_address,
                "user_agent": row.user_agent,
                "created_at": row.created_at,
            }
        )
    return {"items": items, "total": int(total)}


# ---------------------------------------------------------------------------
# Users (§7.2)
# ---------------------------------------------------------------------------


def _user_filters(q: str | None, status: str | None):
    filters = []
    if q:
        pattern = _like(q.strip())
        filters.append(
            or_(
                User.name.ilike(pattern, escape="\\"),
                User.email.ilike(pattern, escape="\\"),
                User.github_username.ilike(pattern, escape="\\"),
            )
        )
    if status:
        if status not in USER_STATUSES:
            raise InvalidQuery(
                f"status must be one of {', '.join(USER_STATUSES)}"
            )
        filters.append(User.status == status)
    return filters


def _user_count_subqueries():
    repo_count = (
        select(func.count(Repository.id))
        .join(Installation, Repository.installation_id == Installation.id)
        .where(
            Installation.user_id == User.id,
            Repository.removed_at.is_(None),
        )
        .correlate(User)
        .scalar_subquery()
    )
    credential_count = (
        select(func.count(ApiKey.id))
        .where(ApiKey.user_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )
    review_count = (
        select(func.count(Review.id))
        .join(PullRequest, Review.pr_id == PullRequest.id)
        .join(Repository, PullRequest.repo_id == Repository.id)
        .join(Installation, Repository.installation_id == Installation.id)
        .where(Installation.user_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )
    return repo_count, credential_count, review_count


async def list_users(
    db: AsyncSession,
    *,
    q: str | None,
    status: str | None,
    sort: str,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    limit, offset = validate_pagination(limit, offset)
    if sort not in USER_SORTS:
        raise InvalidQuery(f"sort must be one of {', '.join(USER_SORTS)}")

    repo_count, credential_count, review_count = _user_count_subqueries()
    order = {
        "created": desc(User.created_at),
        "last_login": desc(User.last_login_at),
        "reviews": desc(review_count),
    }[sort]

    filters = _user_filters(q, status)
    total = (
        await db.execute(select(func.count(User.id)).where(*filters))
    ).scalar_one()
    rows = (
        await db.execute(
            select(
                User.id,
                User.name,
                User.email,
                User.github_username,
                User.created_at,
                User.last_login_at,
                User.status,
                repo_count.label("repo_count"),
                credential_count.label("credential_count"),
                review_count.label("review_count"),
            )
            .where(*filters)
            .order_by(order, desc(User.id))
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return {
        "items": [dict(row._mapping) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def _latest_execution_column(column_factory, correlate_target=Review):
    return (
        select(column_factory())
        .where(
            ReviewExecution.review_id == correlate_target.id,
            ReviewExecution.execution_number == _max_execution_number(),
        )
        .correlate(correlate_target)
        .scalar_subquery()
    )


def _max_execution_number():
    return (
        select(func.max(ReviewExecution.execution_number))
        .where(ReviewExecution.review_id == Review.id)
        .correlate(Review)
        .scalar_subquery()
    )


async def user_detail(
    db: AsyncSession,
    user_id: uuid_lib.UUID,
    *,
    reviews_limit: int,
    reviews_offset: int,
) -> dict[str, Any] | None:
    reviews_limit, reviews_offset = validate_pagination(
        reviews_limit, reviews_offset
    )
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalars().first()
    if user is None:
        return None

    provider_col, model_col, _, mapping_health = _mapping_parts()
    repository_rows = (
        await db.execute(
            _mapping_joins(
                select(
                    Repository.id,
                    Repository.full_name,
                    Repository.is_private,
                    Repository.is_archived,
                    Repository.removed_at,
                    Repository.last_synced_at,
                    provider_col.label("mapping_provider"),
                    model_col.label("mapping_model"),
                    mapping_health.label("mapping_health"),
                )
                .join(
                    Installation,
                    Repository.installation_id == Installation.id,
                )
                .join(User, Installation.user_id == User.id)
            )
            .where(User.id == user_id)
            .order_by(desc(Repository.created_at))
            .limit(MAX_PAGE)
        )
    ).all()

    last_health_status = (
        select(ApiKeyHealth.status)
        .where(ApiKeyHealth.key_id == ApiKey.id)
        .order_by(ApiKeyHealth.checked_at.desc())
        .limit(1)
        .correlate(ApiKey)
        .scalar_subquery()
    )
    last_health_at = (
        select(ApiKeyHealth.checked_at)
        .where(ApiKeyHealth.key_id == ApiKey.id)
        .order_by(ApiKeyHealth.checked_at.desc())
        .limit(1)
        .correlate(ApiKey)
        .scalar_subquery()
    )
    credential_rows = (
        await db.execute(
            select(
                ApiKey.id,
                ApiKey.label,
                ApiKey.provider,
                ApiKey.is_valid,
                ApiKey.is_enabled,
                ApiKey.last_used_at,
                ApiKey.created_at,
                last_health_status.label("last_health_status"),
                last_health_at.label("last_health_at"),
            )
            .where(ApiKey.user_id == user_id)
            .order_by(desc(ApiKey.created_at))
            .limit(MAX_PAGE)
        )
    ).all()

    review_join = (
        select(Review.id)
        .join(PullRequest, Review.pr_id == PullRequest.id)
        .join(Repository, PullRequest.repo_id == Repository.id)
        .join(Installation, Repository.installation_id == Installation.id)
        .where(Installation.user_id == user_id)
        .subquery()
    )
    reviews_total = (
        await db.execute(
            select(func.count()).select_from(review_join)
        )
    ).scalar_one()
    status_rows = (
        await db.execute(
            select(Review.status, func.count(Review.id))
            .join(PullRequest, Review.pr_id == PullRequest.id)
            .join(Repository, PullRequest.repo_id == Repository.id)
            .join(
                Installation, Repository.installation_id == Installation.id
            )
            .where(Installation.user_id == user_id)
            .group_by(Review.status)
        )
    ).all()
    review_status_counts = {status: count for status, count in status_rows}

    latest_provider = _latest_execution_column(
        lambda: ReviewExecution.provider
    )
    latest_model = _latest_execution_column(lambda: ReviewExecution.model)
    latest_status = _latest_execution_column(lambda: ReviewExecution.status)
    latest_duration = _latest_execution_column(
        lambda: ReviewExecution.duration_ms
    )
    latest_error = _latest_execution_column(
        lambda: ReviewExecution.error_message
    )
    review_rows = (
        await db.execute(
            select(
                Review.id,
                Review.status,
                Review.created_at,
                Review.started_at,
                Review.completed_at,
                Repository.full_name.label("repository_full_name"),
                PullRequest.pr_number,
                PullRequest.title.label("pr_title"),
                latest_provider.label("latest_provider"),
                latest_model.label("latest_model"),
                latest_status.label("latest_status"),
                latest_duration.label("latest_duration_ms"),
                latest_error.label("latest_error"),
            )
            .join(PullRequest, Review.pr_id == PullRequest.id)
            .join(Repository, PullRequest.repo_id == Repository.id)
            .join(
                Installation, Repository.installation_id == Installation.id
            )
            .where(Installation.user_id == user_id)
            .order_by(desc(Review.created_at))
            .limit(reviews_limit)
            .offset(reviews_offset)
        )
    ).all()
    reviews = []
    for row in review_rows:
        item = dict(row._mapping)
        item["latest_error"] = (
            sanitize_error_message(item["latest_error"])
            if item["latest_error"]
            else None
        )
        reviews.append(item)

    error_rows = (
        await db.execute(
            select(
                ReviewExecution.provider,
                ReviewExecution.error_message,
                ReviewExecution.started_at,
            )
            .join(Review, Review.id == ReviewExecution.review_id)
            .join(PullRequest, Review.pr_id == PullRequest.id)
            .join(Repository, PullRequest.repo_id == Repository.id)
            .join(
                Installation, Repository.installation_id == Installation.id
            )
            .where(
                Installation.user_id == user_id,
                ReviewExecution.error_message.is_not(None),
            )
            .order_by(desc(ReviewExecution.started_at))
            .limit(10)
        )
    ).all()
    recent_errors = [
        {
            "provider": row.provider,
            "message": sanitize_error_message(row.error_message),
            "occurred_at": row.started_at,
        }
        for row in error_rows
    ]

    audit_rows = (
        await db.execute(
            select(
                AuditLog.id,
                AuditLog.action,
                AuditLog.actor_id,
                AuditLog.actor_type,
                AuditLog.details,
                AuditLog.created_at,
            )
            .where(AuditLog.entity_id == str(user_id))
            .order_by(desc(AuditLog.created_at))
            .limit(50)
        )
    ).all()
    audit_events = []
    for row in audit_rows:
        details = row.details or {}
        audit_events.append(
            {
                "id": row.id,
                "action": row.action,
                "actor_id": row.actor_id,
                "actor_type": row.actor_type,
                "outcome": details.get("outcome"),
                "created_at": row.created_at,
            }
        )

    return {
        "profile": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "github_username": user.github_username,
            "avatar_url": user.avatar_url,
            "role": user.role,
            "status": user.status,
            "is_verified": user.is_verified,
            "default_provider": user.default_provider,
            "created_at": user.created_at,
            "disabled_at": user.disabled_at,
            "last_login_at": user.last_login_at,
            "last_active_at": user.last_active_at,
        },
        "repositories": [dict(row._mapping) for row in repository_rows],
        "credentials": [dict(row._mapping) for row in credential_rows],
        "reviews": {
            "items": reviews,
            "total": reviews_total,
            "status_counts": review_status_counts,
        },
        "recent_errors": recent_errors,
        "audit_events": audit_events,
    }


# ---------------------------------------------------------------------------
# Repositories (§7.3)
# ---------------------------------------------------------------------------


async def list_repositories(
    db: AsyncSession,
    *,
    user: str | None,
    provider: str | None,
    mapping: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    limit, offset = validate_pagination(limit, offset)
    if mapping and mapping not in MAPPING_STATES:
        raise InvalidQuery(
            f"mapping must be one of {', '.join(MAPPING_STATES)}"
        )

    provider_col, model_col, _, mapping_health = _mapping_parts()

    filters = []
    if user:
        try:
            filters.append(User.id == uuid_lib.UUID(user))
        except ValueError:
            pattern = _like(user.strip())
            filters.append(
                or_(
                    User.email.ilike(pattern, escape="\\"),
                    User.github_username.ilike(pattern, escape="\\"),
                    User.name.ilike(pattern, escape="\\"),
                )
            )
    if provider:
        executions_match = (
            select(ReviewExecution.id)
            .join(Review, Review.id == ReviewExecution.review_id)
            .join(PullRequest, Review.pr_id == PullRequest.id)
            .where(
                PullRequest.repo_id == Repository.id,
                ReviewExecution.provider == provider,
            )
            .correlate(Repository)
            .exists()
        )
        filters.append(
            or_(provider_col == provider, executions_match)
        )
    if mapping:
        filters.append(mapping_health == mapping)

    review_count = (
        select(func.count(Review.id))
        .join(PullRequest, Review.pr_id == PullRequest.id)
        .where(PullRequest.repo_id == Repository.id)
        .correlate(Repository)
        .scalar_subquery()
    )
    last_review_at = (
        select(func.max(Review.created_at))
        .join(PullRequest, Review.pr_id == PullRequest.id)
        .where(PullRequest.repo_id == Repository.id)
        .correlate(Repository)
        .scalar_subquery()
    )
    failures_7d = (
        select(func.count(ReviewExecution.id))
        .join(Review, Review.id == ReviewExecution.review_id)
        .join(PullRequest, Review.pr_id == PullRequest.id)
        .where(
            PullRequest.repo_id == Repository.id,
            ReviewExecution.status == "failed",
            ReviewExecution.started_at
            >= datetime.now(UTC) - timedelta(days=7),
        )
        .correlate(Repository)
        .scalar_subquery()
    )

    base = (
        select(
            Repository.id,
            Repository.full_name,
            Repository.is_private,
            Repository.is_archived,
            Repository.removed_at,
            Repository.created_at,
            Repository.last_synced_at,
            User.id.label("owner_id"),
            User.email.label("owner_email"),
            User.github_username.label("owner_github_username"),
            Installation.account_login.label("installation_account_login"),
            Installation.suspended_at.label("installation_suspended_at"),
            Installation.permissions_ok.label("installation_permissions_ok"),
            provider_col.label("mapping_provider"),
            model_col.label("mapping_model"),
            mapping_health.label("mapping_health"),
            review_count.label("review_count"),
            last_review_at.label("last_review_at"),
            failures_7d.label("recent_failures_7d"),
        )
        .join(Installation, Repository.installation_id == Installation.id)
        .join(User, Installation.user_id == User.id)
    )
    base = _mapping_joins(base)

    total = (
        await db.execute(
            _mapping_joins(
                select(func.count(Repository.id))
                .join(
                    Installation,
                    Repository.installation_id == Installation.id,
                )
                .join(User, Installation.user_id == User.id)
            ).where(*filters)
        )
    ).scalar_one()

    rows = (
        await db.execute(
            base.where(*filters)
            .order_by(desc(last_review_at).nullslast(), desc(Repository.created_at))
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return {
        "items": [dict(row._mapping) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ---------------------------------------------------------------------------
# Reviews (§7.3)
# ---------------------------------------------------------------------------


async def list_reviews(
    db: AsyncSession,
    *,
    user: str | None,
    repo: str | None,
    provider: str | None,
    model: str | None,
    status: str | None,
    error: str | None,
    period: str | None,
    start: str | None,
    end: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    limit, offset = validate_pagination(limit, offset)

    filters = []
    if period is not None:
        _, start_dt, end_dt = resolve_period(period, start, end)
        filters.append(Review.created_at >= start_dt)
        filters.append(Review.created_at < end_dt)
    if user:
        try:
            filters.append(User.id == uuid_lib.UUID(user))
        except ValueError:
            pattern = _like(user.strip())
            filters.append(
                or_(
                    User.email.ilike(pattern, escape="\\"),
                    User.github_username.ilike(pattern, escape="\\"),
                    User.name.ilike(pattern, escape="\\"),
                )
            )
    if repo:
        try:
            filters.append(Repository.id == uuid_lib.UUID(repo))
        except ValueError:
            filters.append(
                Repository.full_name.ilike(_like(repo.strip()), escape="\\")
            )
    if status:
        filters.append(Review.status == status)

    latest_provider_col = _latest_execution_column(
        lambda: ReviewExecution.provider
    )
    latest_model_col = _latest_execution_column(lambda: ReviewExecution.model)
    latest_status_col = _latest_execution_column(
        lambda: ReviewExecution.status
    )
    latest_duration_col = _latest_execution_column(
        lambda: ReviewExecution.duration_ms
    )
    latest_error_col = _latest_execution_column(
        lambda: ReviewExecution.error_message
    )

    if provider:
        filters.append(latest_provider_col == provider)
    if model:
        filters.append(latest_model_col == model)
    if error:
        if error == "none":
            filters.append(latest_error_col.is_(None))
        else:
            filters.append(
                latest_error_col.ilike(_like(error.strip()), escape="\\")
            )

    configured_provider, configured_model, _, _ = _mapping_parts()

    joins = (
        select(
            Review.id,
            Review.status,
            Review.created_at,
            Review.started_at,
            Review.completed_at,
            Repository.id.label("repository_id"),
            Repository.full_name.label("repository_full_name"),
            PullRequest.pr_number,
            PullRequest.title.label("pr_title"),
            User.email.label("owner_email"),
            configured_provider.label("configured_provider"),
            configured_model.label("configured_model"),
            latest_provider_col.label("provider"),
            latest_model_col.label("model"),
            latest_status_col.label("execution_status"),
            latest_duration_col.label("duration_ms"),
            latest_error_col.label("error"),
        )
        .join(PullRequest, Review.pr_id == PullRequest.id)
        .join(Repository, PullRequest.repo_id == Repository.id)
        .join(Installation, Repository.installation_id == Installation.id)
        .join(User, Installation.user_id == User.id)
    )

    total = (
        await db.execute(
            select(func.count(Review.id))
            .join(PullRequest, Review.pr_id == PullRequest.id)
            .join(Repository, PullRequest.repo_id == Repository.id)
            .join(
                Installation, Repository.installation_id == Installation.id
            )
            .join(User, Installation.user_id == User.id)
            .where(*filters)
        )
    ).scalar_one()

    rows = (
        await db.execute(
            joins.where(*filters)
            .order_by(desc(Review.created_at), desc(Review.id))
            .limit(limit)
            .offset(offset)
        )
    ).all()
    items = []
    for row in rows:
        item = dict(row._mapping)
        item["error"] = (
            sanitize_error_message(item["error"]) if item["error"] else None
        )
        items.append(item)
    return {"items": items, "total": total, "limit": limit, "offset": offset}
