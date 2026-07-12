import uuid
import logging
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

DEFAULT_RULES = [
    "Do not introduce new dependencies without justification",
    "Follow existing naming conventions in the codebase",
    "Add error handling for external API calls",
    "Keep functions under 50 lines where possible",
    "Use descriptive variable and function names",
    "Add type hints for Python functions",
    "Prefer composition over inheritance",
    "Handle edge cases and null values",
]


async def load_rules(repo_id: uuid.UUID) -> List[str]:
    rules = list(DEFAULT_RULES)

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select("rule_text")
                .select_from("repository_rules")
                .where("repo_id" == repo_id, "is_active" == True)
                .order_by("priority" == False)
            )
            rows = result.fetchall()
            for row in rows:
                if row[0] not in rules:
                    rules.append(row[0])
    except Exception as e:
        logger.warning(f"Failed to load repo rules: {e}")

    return rules


async def add_rule(repo_id: uuid.UUID, rule_text: str, rule_type: str = "general", priority: int = 0) -> None:
    import uuid as _uuid
    from datetime import datetime, timezone

    async with AsyncSessionLocal() as db:
        await db.execute(
            "INSERT INTO repository_rules (id, repo_id, rule_type, rule_text, priority, is_active, created_at) VALUES (:id, :repo_id, :rt, :text, :p, true, :now)",
            {"id": _uuid.uuid4(), "repo_id": repo_id, "rt": rule_type, "text": rule_text, "p": priority, "now": datetime.now(timezone.utc)},
        )
        await db.commit()
