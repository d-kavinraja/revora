"""Persistent repository knowledge management.

Stores and retrieves repository knowledge (conventions, summaries, rules)
with DB-backed persistence and content hashing for cache invalidation.
"""

import uuid
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional, Dict

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.knowledge import RepositoryKnowledge, RepositoryRule
from app.models.github import Repository
from app.knowledge.convention_detector import detect_conventions
from app.knowledge.rule_engine import load_rules

logger = logging.getLogger(__name__)

KNOWLEDGE_TYPES = [
    "repo_summary",
    "architecture_summary",
    "folder_summary",
    "coding_conventions",
    "naming_conventions",
    "review_rules",
    "security_rules",
    "historical_learnings",
]


class KnowledgeStore:
    """Manages persistent repository knowledge."""

    async def load_knowledge(
        self,
        repo_id: uuid.UUID,
        knowledge_type: str,
    ) -> Optional[Dict]:
        """Load knowledge by repo_id and type.

        Args:
            repo_id: Repository UUID.
            knowledge_type: Type of knowledge to load.

        Returns:
            Dict with content, metadata, content_hash or None.
        """
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(
                        RepositoryKnowledge.content,
                        RepositoryKnowledge.extra_metadata,
                        RepositoryKnowledge.content_hash,
                    ).where(
                        RepositoryKnowledge.repo_id == repo_id,
                        RepositoryKnowledge.knowledge_type == knowledge_type,
                    )
                )
                row = result.first()
                if row:
                    return {
                        "content": row[0],
                        "metadata": row[1],
                        "content_hash": row[2],
                    }
        except Exception as e:
            logger.error(
                f"Failed to load knowledge for repo {repo_id}, "
                f"type {knowledge_type}: {e}"
            )
        return None

    async def save_knowledge(
        self,
        repo_id: uuid.UUID,
        knowledge_type: str,
        content: str,
        metadata: Optional[Dict] = None,
    ) -> None:
        """Save or update knowledge for a repository.

        Args:
            repo_id: Repository UUID.
            knowledge_type: Type of knowledge.
            content: Knowledge content.
            metadata: Optional metadata dict.
        """
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        try:
            async with AsyncSessionLocal() as db:
                # Check for existing record
                existing = await db.execute(
                    select(RepositoryKnowledge.id).where(
                        RepositoryKnowledge.repo_id == repo_id,
                        RepositoryKnowledge.knowledge_type == knowledge_type,
                    )
                )
                row = existing.first()

                now = datetime.now(timezone.utc)

                if row:
                    # Update existing
                    await db.execute(
                        text(
                            "UPDATE repository_knowledge "
                            "SET content = :content, "
                            "extra_metadata = :metadata, "
                            "content_hash = :hash, "
                            "updated_at = :now "
                            "WHERE repo_id = :repo_id "
                            "AND knowledge_type = :kt"
                        ),
                        {
                            "content": content,
                            "metadata": str(metadata or {}),
                            "hash": content_hash,
                            "now": now,
                            "repo_id": repo_id,
                            "kt": knowledge_type,
                        },
                    )
                else:
                    # Insert new
                    await db.execute(
                        text(
                            "INSERT INTO repository_knowledge "
                            "(id, repo_id, knowledge_type, content, "
                            "extra_metadata, content_hash, created_at, updated_at) "
                            "VALUES (:id, :repo_id, :kt, :content, "
                            ":metadata, :hash, :now, :now)"
                        ),
                        {
                            "id": uuid.uuid4(),
                            "repo_id": repo_id,
                            "kt": knowledge_type,
                            "content": content,
                            "metadata": str(metadata or {}),
                            "hash": content_hash,
                            "now": now,
                        },
                    )

                await db.commit()

        except Exception as e:
            logger.error(
                f"Failed to save knowledge for repo {repo_id}, "
                f"type {knowledge_type}: {e}"
            )

    async def load_or_generate_conventions(
        self,
        repo_id: uuid.UUID,
        repo_path: str,
    ) -> str:
        """Load conventions from cache or generate from repo.

        Args:
            repo_id: Repository UUID.
            repo_path: Path to repository root.

        Returns:
            Detected conventions as string.
        """
        existing = await self.load_knowledge(repo_id, "coding_conventions")
        if existing:
            return existing["content"]

        conventions = detect_conventions(repo_path)
        await self.save_knowledge(repo_id, "coding_conventions", conventions)
        return conventions

    async def load_rules(self, repo_id: uuid.UUID):
        """Load review rules from database.

        Args:
            repo_id: Repository UUID.

        Returns:
            List of rule strings.
        """
        return await load_rules(repo_id)

    async def invalidate_cache(
        self,
        repo_id: uuid.UUID,
        knowledge_type: Optional[str] = None,
    ) -> None:
        """Invalidate cached knowledge for a repository.

        Args:
            repo_id: Repository UUID.
            knowledge_type: Optional specific type to invalidate.
                           If None, invalidates all types.
        """
        try:
            async with AsyncSessionLocal() as db:
                if knowledge_type:
                    await db.execute(
                        text(
                            "DELETE FROM repository_knowledge "
                            "WHERE repo_id = :repo_id "
                            "AND knowledge_type = :kt"
                        ),
                        {"repo_id": repo_id, "kt": knowledge_type},
                    )
                else:
                    await db.execute(
                        text(
                            "DELETE FROM repository_knowledge "
                            "WHERE repo_id = :repo_id"
                        ),
                        {"repo_id": repo_id},
                    )
                await db.commit()

        except Exception as e:
            logger.error(
                f"Failed to invalidate cache for repo {repo_id}: {e}"
            )


knowledge_store = KnowledgeStore()
