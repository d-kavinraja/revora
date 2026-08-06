"""RepositoryService — repository lifecycle management.

Handles add, remove, sync, and refresh-installation operations while
preserving review history and audit logs.

GitHub is the single source of truth for repository membership: the GitHub
App installation is the only place where repositories are added or removed.
Revora never removes a repository from the installation itself. Removed
repositories are never deleted locally: they are marked (removed_at),
unlinked from their installation, and hidden from the active list. All
history (PRs, reviews, executions, analytics) is preserved. Re-installing
the GitHub App re-links the same repository row and resumes monitoring.
"""

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.github import Installation, Repository
from app.models.sync_run import SYNC_REASON_MANUAL

logger = logging.getLogger(__name__)


class RepositoryService:
    """Manages repository lifecycle operations."""

    async def refresh_installation(
        self,
        db,
        user_id: UUID,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        """Fetch all repositories from GitHub App installations and sync to local DB.

        Delegates to the sync engine (manual reason) so the behavior — and the
        bugs it fixes (no history-destroying deletes, reviews_enabled preserved,
        permissions gate) — is identical between manual and automatic syncs.
        """
        from app.services.sync_engine import run_sync_pass

        result = await run_sync_pass(
            reason=SYNC_REASON_MANUAL,
            user_id=user_id,
            use_advisory_lock=True,
        )
        counts = result.get("counts", {})
        failures = result.get("failures", {})

        # Audit log
        await self._audit(
            db,
            actor_id=str(user_id),
            action="installation.refreshed",
            entity_type="installation",
            entity_id=str(user_id),
            details={
                "new_count": counts.get("repos_added", 0),
                "removed_count": counts.get("repos_removed", 0),
                "updated_count": counts.get("repos_updated", 0),
                "jobs_enqueued": counts.get("jobs_enqueued", 0),
                "sync_reason": SYNC_REASON_MANUAL,
                "sync_status": result.get("status"),
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )

        return {
            "status": result.get("status", "success") if not failures else "partial",
            "message": (
                f"Synced {counts.get('repo_count', 0)} repositories from GitHub."
                if not failures
                else f"Synced with {len(failures)} failure(s): {list(failures)[:3]}"
            ),
            "new_count": counts.get("repos_added", 0),
            "removed_count": counts.get("repos_removed", 0),
            "updated_count": counts.get("repos_updated", 0),
            "failed_count": len(failures),
            "failures": failures,
            "synced": [],
        }

    async def get_repository_status(
        self,
        db,
        repo_id: UUID,
        user_id: UUID,
    ) -> dict[str, Any]:
        """Get detailed status for a repository including GitHub state."""
        inst_result = await db.execute(
            select(Installation).where(Installation.user_id == user_id)
        )
        install_ids = [i.id for i in inst_result.scalars().all()]

        repo_result = await db.execute(
            select(Repository).where(
                Repository.id == repo_id,
                Repository.installation_id.in_(install_ids),
            )
        )
        repo = repo_result.scalars().first()
        if not repo:
            raise ValueError("Repository not found.")

        return {
            "id": str(repo.id),
            "full_name": repo.full_name,
            "status": "removed" if repo.removed_at else "active",
            "removed_at": repo.removed_at.isoformat() if repo.removed_at else None,
            "reviews_enabled": repo.reviews_enabled,
            "is_archived": repo.is_archived,
            "last_synced_at": repo.last_synced_at.isoformat() if repo.last_synced_at else None,
            "settings": repo.settings or {},
            "permissions": {},
        }

    async def _audit(self, db, actor_id, action, entity_type, entity_id, details, ip_address=None, user_agent=None):
        """Write an audit log entry (best-effort)."""
        try:
            entry = AuditLog(
                actor_id=actor_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                details=details,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            db.add(entry)
            await db.commit()
        except Exception as e:
            logger.warning(f"Audit log failed for {action}: {e}")


repository_service = RepositoryService()
