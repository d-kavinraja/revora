"""Resolved provider/model selection snapshots for review executions.

This module is a thin layer over ``resolve_provider_config``: it does not
introduce a second routing engine. Every review execution records where its
selection came from (repository mapping or global routing) so the UI can show
configured, selected and actually-executed values separately.

The snapshot lives in the existing ``ReviewExecution.configuration_snapshot``
JSON column, so no schema migration is required.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import ReviewExecution
from app.models.github import Repository
from app.orchestrator.models import (
    CONFIG_SOURCE_NONE,
    CONFIG_SOURCE_REPO,
    CONFIG_SOURCE_ROUTING,
)
from app.services.provider_registry import (
    ProviderUnavailableError,
    provider_registry_service,
)

SELECTION_SNAPSHOT_KEY = "selection"

_API_SOURCE = {
    CONFIG_SOURCE_REPO: "repository_mapping",
    CONFIG_SOURCE_ROUTING: "routing_fallback",
    CONFIG_SOURCE_NONE: "unresolved",
}


@dataclass(frozen=True)
class ResolvedSelection:
    """One review execution's immutable provider/model selection."""

    provider: str | None
    provider_slug: str | None
    provider_name: str | None
    model: str | None
    api_key_id: str | None
    source: str
    repository_mapping_status: str
    repository_provider: str | None
    repository_model: str | None
    error: str | None = None
    resolved_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

    @property
    def is_resolved(self) -> bool:
        return bool(self.provider and self.model)


async def resolve_selection(
    db: AsyncSession,
    user_id: str,
    db_repo: Repository | None,
) -> ResolvedSelection:
    """Resolve a repository mapping or routing fallback for one execution.

    Reuses :func:`app.github.shared.resolve_provider_config`; only the
    snapshot/canonicalisation layer is new. A blocked provider does not raise
    here: the selection records ``error`` so the review can be shown as a
    configuration failure instead of silently falling back to another model.
    """
    from app.github.shared import resolve_provider_config

    repo_settings = dict(db_repo.settings or {}) if db_repo else {}
    repo_provider = repo_settings.get("assigned_provider")
    repo_model = repo_settings.get("assigned_model")
    mapping_status = "mapped" if repo_provider and repo_model else "not_mapped"

    error: str | None = None
    try:
        provider, model, api_key_id, source = await resolve_provider_config(
            db, user_id, db_repo
        )
    except ProviderUnavailableError as exc:
        provider = None
        model = None
        api_key_id = None
        source = CONFIG_SOURCE_NONE
        error = exc.message

    provider_slug = None
    provider_name = None
    if provider:
        row = await provider_registry_service.get_by_identifier(db, provider)
        if row is not None:
            provider_slug = row.slug
            provider_name = row.display_name
        else:
            provider_slug = provider
            provider_name = provider

    return ResolvedSelection(
        provider=provider,
        provider_slug=provider_slug,
        provider_name=provider_name,
        model=model,
        api_key_id=api_key_id,
        source=source,
        repository_mapping_status=mapping_status,
        repository_provider=repo_provider,
        repository_model=repo_model,
        error=error,
    )


def selection_snapshot(selection: ResolvedSelection) -> dict[str, Any]:
    """Serializable snapshot stored under ``configuration_snapshot.selection``."""
    return {
        "repository_mapping_status": selection.repository_mapping_status,
        "repository_provider": selection.repository_provider,
        "repository_model": selection.repository_model,
        "selection_source": selection.source,
        "selected_provider": selection.provider,
        "selected_provider_slug": selection.provider_slug,
        "selected_provider_name": selection.provider_name,
        "selected_model": selection.model,
        "selected_api_key_id": selection.api_key_id,
        "error": selection.error,
        "resolved_at": selection.resolved_at,
    }


def merge_configuration_snapshot(
    existing: dict[str, Any] | None,
    selection: ResolvedSelection,
) -> dict[str, Any]:
    snapshot = dict(existing or {})
    snapshot[SELECTION_SNAPSHOT_KEY] = selection_snapshot(selection)
    return snapshot


def read_selection_snapshot(
    execution: ReviewExecution | None,
) -> dict[str, Any] | None:
    if execution is None:
        return None
    snapshot = execution.configuration_snapshot or {}
    if not isinstance(snapshot, dict):
        return None
    value = snapshot.get(SELECTION_SNAPSHOT_KEY)
    return value if isinstance(value, dict) else None


def selection_from_snapshot(
    execution: ReviewExecution,
    snapshot: dict[str, Any],
) -> ResolvedSelection:
    return ResolvedSelection(
        provider=snapshot.get("selected_provider"),
        provider_slug=snapshot.get("selected_provider_slug"),
        provider_name=snapshot.get("selected_provider_name"),
        model=snapshot.get("selected_model"),
        api_key_id=(
            snapshot.get("selected_api_key_id")
            or (str(execution.api_key_id) if execution.api_key_id else None)
        ),
        source=snapshot.get("selection_source") or CONFIG_SOURCE_NONE,
        repository_mapping_status=(
            snapshot.get("repository_mapping_status") or "unknown"
        ),
        repository_provider=snapshot.get("repository_provider"),
        repository_model=snapshot.get("repository_model"),
        error=snapshot.get("error"),
        resolved_at=snapshot.get("resolved_at")
        or datetime.now(UTC).isoformat(),
    )


def apply_selection_to_execution(
    execution: ReviewExecution,
    selection: ResolvedSelection,
) -> None:
    """Persist the selected provider/model on the execution row.

    ``provider``/``model`` remain the selected values until completion records
    the actual execution. This preserves backwards compatibility for callers
    that read the columns while the review is queued or running.
    """
    if selection.provider:
        execution.provider = selection.provider
    if selection.model:
        execution.model = selection.model
    if selection.api_key_id:
        try:
            execution.api_key_id = uuid.UUID(str(selection.api_key_id))
        except (ValueError, TypeError):
            pass
    execution.configuration_snapshot = merge_configuration_snapshot(
        execution.configuration_snapshot, selection
    )


def _api_source(source: str | None) -> str:
    if not source:
        return "unknown"
    if source in _API_SOURCE:
        return _API_SOURCE[source]
    return "unknown"


def selection_api_fields(execution: ReviewExecution | None) -> dict[str, Any]:
    """Safe, API-ready selection/actual projection.

    Never returns API keys, tokens, credentials or raw repository settings.
    Legacy executions without a snapshot report ``unknown`` rather than
    guessing whether the repository mapping or routing produced the model.
    """
    if execution is None:
        return selection_api_fields_from_values(None, None, None, None, None, None)
    return selection_api_fields_from_values(
        execution.configuration_snapshot,
        execution.provider,
        execution.model,
        execution.status,
        execution.started_at,
        execution.stats,
    )


def selection_api_fields_from_values(
    configuration_snapshot: dict[str, Any] | None,
    provider: str | None,
    model: str | None,
    status: str | None,
    started_at: Any,
    stats: dict[str, Any] | None,
) -> dict[str, Any]:
    snapshot = None
    if isinstance(configuration_snapshot, dict):
        value = configuration_snapshot.get(SELECTION_SNAPSHOT_KEY)
        if isinstance(value, dict):
            snapshot = value

    if snapshot:
        selected_provider = snapshot.get("selected_provider")
        selected_provider_slug = snapshot.get("selected_provider_slug")
        selected_provider_name = snapshot.get("selected_provider_name")
        selected_model = snapshot.get("selected_model")
        source = _api_source(snapshot.get("selection_source"))
        mapping_status = snapshot.get("repository_mapping_status") or "unknown"
        repository_provider = snapshot.get("repository_provider")
        repository_model = snapshot.get("repository_model")
    else:
        # Legacy row: the column may hold the selected (pre-inference) or the
        # actual (completed) value. Never claim a source we did not record.
        selected_provider = provider
        selected_provider_slug = provider
        selected_provider_name = provider
        selected_model = model
        source = "unknown" if (selected_provider or selected_model) else "unresolved"
        mapping_status = "unknown"
        repository_provider = None
        repository_model = None

    stats = stats or {}
    execution_started = started_at is not None
    actual_provider = stats.get("provider")
    actual_model = stats.get("model")
    if execution_started and not actual_provider and status == "completed":
        # Older completed rows stored the actual execution on the columns
        # instead of stats. Only trust this for completed executions.
        actual_provider = provider
        actual_model = model

    return {
        "repository_mapping_status": mapping_status,
        "repository_provider": repository_provider,
        "repository_model": repository_model,
        "selection_source": source,
        "selected_provider": selected_provider,
        "selected_provider_slug": selected_provider_slug,
        "selected_provider_name": selected_provider_name,
        "selected_model": selected_model,
        "actual_execution_provider": actual_provider,
        "actual_execution_model": actual_model,
        "execution_status": status,
        "execution_started": execution_started,
    }
