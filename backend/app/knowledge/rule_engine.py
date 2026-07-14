"""Repository rule engine.

Loads and manages review rules from the database with sensible defaults.
Rules can be customized per repository.
"""

import uuid
import logging
from typing import List
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.knowledge import RepositoryRule

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
    """Load review rules from database with defaults.

    Args:
        repo_id: Repository UUID.

    Returns:
        List of rule strings (defaults + custom rules).
    """
    rules = list(DEFAULT_RULES)

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(RepositoryRule.rule_text).where(
                    RepositoryRule.repo_id == repo_id,
                    RepositoryRule.is_active == True,
                ).order_by(RepositoryRule.priority.desc())
            )
            rows = result.fetchall()
            for row in rows:
                if row[0] not in rules:
                    rules.append(row[0])
    except Exception as e:
        logger.warning(f"Failed to load repo rules for {repo_id}: {e}")

    return rules


async def add_rule(
    repo_id: uuid.UUID,
    rule_text: str,
    rule_type: str = "general",
    priority: int = 0,
) -> None:
    """Add a review rule for a repository.

    Args:
        repo_id: Repository UUID.
        rule_text: The rule text.
        rule_type: Type of rule (general, security, performance, etc.).
        priority: Rule priority (higher = more important).
    """
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text(
                    "INSERT INTO repository_rules "
                    "(id, repo_id, rule_type, rule_text, priority, "
                    "is_active, created_at) "
                    "VALUES (:id, :repo_id, :rt, :text, :p, true, :now)"
                ),
                {
                    "id": uuid.uuid4(),
                    "repo_id": repo_id,
                    "rt": rule_type,
                    "text": rule_text,
                    "p": priority,
                    "now": datetime.now(timezone.utc),
                },
            )
            await db.commit()

    except Exception as e:
        logger.error(f"Failed to add rule for repo {repo_id}: {e}")


async def remove_rule(repo_id: uuid.UUID, rule_text: str) -> None:
    """Deactivate a review rule.

    Args:
        repo_id: Repository UUID.
        rule_text: The rule text to deactivate.
    """
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text(
                    "UPDATE repository_rules "
                    "SET is_active = false "
                    "WHERE repo_id = :repo_id AND rule_text = :text"
                ),
                {"repo_id": repo_id, "text": rule_text},
            )
            await db.commit()

    except Exception as e:
        logger.error(f"Failed to remove rule for repo {repo_id}: {e}")
