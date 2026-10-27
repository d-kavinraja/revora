"""Audit helper for administrative actions.

Writes `audit_logs` rows with `actor_type="admin"` (or `"system"` for
CLI/startup bootstrap) plus actor, action, target, timestamp, outcome and
whitelisted scalar metadata. Never records secrets (no keys, tokens,
hashes, passwords or message bodies).
"""

from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import AdminUser
from app.models.audit import AuditLog


async def admin_audit(
    db: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    outcome: str = "success",
    details: dict[str, Any] | None = None,
    admin: AdminUser | None = None,
    actor_id: str | None = None,
    actor_type: str | None = None,
    request: Request | None = None,
    commit: bool = True,
) -> AuditLog:
    """Record one administrative audit event.

    `admin` (when provided) supplies the actor identity; otherwise
    `actor_id`/`actor_type` overrides are used, defaulting to a system
    actor. `details` must contain whitelisted scalars only.
    """
    resolved_actor_type = actor_type or ("admin" if admin is not None else "system")
    resolved_actor_id = actor_id or (admin.username if admin is not None else None)

    payload = dict(details or {})
    payload["outcome"] = outcome

    user_agent = request.headers.get("user-agent") if request is not None else None
    if user_agent:
        user_agent = user_agent[:500]

    log = AuditLog(
        actor_id=resolved_actor_id,
        actor_type=resolved_actor_type,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id[:100],
        details=payload,
        ip_address=(
            request.client.host
            if request is not None and request.client is not None
            else None
        ),
        user_agent=user_agent,
    )
    db.add(log)
    if commit:
        await db.commit()
    return log
