import uuid
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
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

    async def load_knowledge(self, repo_id: uuid.UUID, knowledge_type: str) -> Optional[Dict]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select("content", "metadata", "content_hash")
                .select_from("repository_knowledge")
                .where(
                    "repo_id" == repo_id,
                    "knowledge_type" == knowledge_type,
                )
            )
            row = result.first()
            if row:
                return {"content": row[0], "metadata": row[1], "content_hash": row[2]}
        return None

    async def save_knowledge(
        self,
        repo_id: uuid.UUID,
        knowledge_type: str,
        content: str,
        metadata: Optional[Dict] = None,
    ) -> None:
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        async with AsyncSessionLocal() as db:
            existing = await db.execute(
                select("id")
                .select_from("repository_knowledge")
                .where(
                    "repo_id" == repo_id,
                    "knowledge_type" == knowledge_type,
                )
            )
            row = existing.first()

            if row:
                await db.execute(
                    "UPDATE repository_knowledge SET content = :content, metadata = :metadata, content_hash = :hash, updated_at = :now WHERE repo_id = :repo_id AND knowledge_type = :kt",
                    {"content": content, "metadata": str(metadata or {}), "hash": content_hash, "now": datetime.now(timezone.utc), "repo_id": repo_id, "kt": knowledge_type},
                )
            else:
                await db.execute(
                    "INSERT INTO repository_knowledge (id, repo_id, knowledge_type, content, metadata, content_hash, created_at, updated_at) VALUES (:id, :repo_id, :kt, :content, :metadata, :hash, :now, :now)",
                    {"id": uuid.uuid4(), "repo_id": repo_id, "kt": knowledge_type, "content": content, "metadata": str(metadata or {}), "hash": content_hash, "now": datetime.now(timezone.utc)},
                )
            await db.commit()

    async def load_or_generate_conventions(self, repo_id: uuid.UUID, repo_path: str) -> str:
        existing = await self.load_knowledge(repo_id, "coding_conventions")
        if existing:
            return existing["content"]

        conventions = detect_conventions(repo_path)
        await self.save_knowledge(repo_id, "coding_conventions", conventions)
        return conventions

    async def load_rules(self, repo_id: uuid.UUID) -> List[str]:
        return await load_rules(repo_id)

    async def invalidate_cache(self, repo_id: uuid.UUID, knowledge_type: Optional[str] = None) -> None:
        async with AsyncSessionLocal() as db:
            if knowledge_type:
                await db.execute(
                    "DELETE FROM repository_knowledge WHERE repo_id = :repo_id AND knowledge_type = :kt",
                    {"repo_id": repo_id, "kt": knowledge_type},
                )
            else:
                await db.execute(
                    "DELETE FROM repository_knowledge WHERE repo_id = :repo_id",
                    {"repo_id": repo_id},
                )
            await db.commit()


knowledge_store = KnowledgeStore()
