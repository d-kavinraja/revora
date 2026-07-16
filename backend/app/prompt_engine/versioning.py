"""Prompt version management.

Supports prompt versioning, A/B testing, rollback, and comparison.
"""

import time
import logging
import hashlib
from typing import Optional, Dict, List
from dataclasses import dataclass, field

from app.prompt_engine.models import CompiledPrompt, PromptVersion

logger = logging.getLogger(__name__)


@dataclass
class PromptVersionRecord:
    """Record of a prompt version."""
    version: str
    template_name: str
    prompt_hash: str
    provider: str
    model: str
    token_budget: int
    created_at: float
    metadata: dict = field(default_factory=dict)


class PromptVersionManager:
    """Manages prompt versions for A/B testing and rollback."""

    def __init__(self):
        self._versions: Dict[str, List[PromptVersionRecord]] = {}
        self._active: Dict[str, str] = {}

    async def register_version(
        self,
        template_name: str,
        version: str,
        prompt: CompiledPrompt,
    ) -> str:
        """Register a new prompt version."""
        prompt_hash = hashlib.sha256(
            (prompt.system_prompt + prompt.user_prompt).encode()
        ).hexdigest()[:16]

        record = PromptVersionRecord(
            version=version,
            template_name=template_name,
            prompt_hash=prompt_hash,
            provider=prompt.provider_metadata.provider,
            model=prompt.provider_metadata.model,
            token_budget=prompt.token_metadata.budget_limit,
            created_at=time.time(),
            metadata={
                "total_tokens": prompt.total_tokens,
                "sections_count": len(prompt.sections),
                "review_type": prompt.review_type,
            },
        )

        if template_name not in self._versions:
            self._versions[template_name] = []
        self._versions[template_name].append(record)
        self._active[template_name] = version

        logger.info(f"Registered prompt version {version} for {template_name}")
        return prompt_hash

    async def get_version(self, template_name: str, version: str) -> Optional[PromptVersionRecord]:
        """Get a specific prompt version."""
        versions = self._versions.get(template_name, [])
        for v in versions:
            if v.version == version:
                return v
        return None

    async def list_versions(self, template_name: str) -> List[PromptVersionRecord]:
        """List all versions for a template."""
        return self._versions.get(template_name, [])

    async def get_active_version(self, template_name: str) -> Optional[str]:
        """Get the active version for a template."""
        return self._active.get(template_name)

    async def rollback(self, template_name: str, target_version: str) -> bool:
        """Rollback to a previous version."""
        record = await self.get_version(template_name, target_version)
        if record:
            self._active[template_name] = target_version
            logger.info(f"Rolled back {template_name} to version {target_version}")
            return True
        return False

    async def compare(self, version_a: str, version_b: str) -> dict:
        """Compare two versions across all templates."""
        results = {}
        for template_name, versions in self._versions.items():
            record_a = None
            record_b = None
            for v in versions:
                if v.version == version_a:
                    record_a = v
                if v.version == version_b:
                    record_b = v

            if record_a and record_b:
                results[template_name] = {
                    "version_a": {
                        "version": record_a.version,
                        "hash": record_a.prompt_hash,
                        "tokens": record_a.metadata.get("total_tokens", 0),
                    },
                    "version_b": {
                        "version": record_b.version,
                        "hash": record_b.prompt_hash,
                        "tokens": record_b.metadata.get("total_tokens", 0),
                    },
                    "same_hash": record_a.prompt_hash == record_b.prompt_hash,
                }

        return results


version_manager = PromptVersionManager()
