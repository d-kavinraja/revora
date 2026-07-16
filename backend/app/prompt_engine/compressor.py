"""Context compression for prompt building.

Applies compression strategies to reduce token usage while preserving
essential information for the review.
"""

import logging
import hashlib
from typing import Dict, List, Optional, Set

from app.prompt_engine.models import PromptSection, PromptBuildRequest
from app.prompt_engine.token_budget import estimate_tokens

logger = logging.getLogger(__name__)


class PromptCompressor:
    """Compresses prompt sections to reduce token usage."""

    async def compress_sections(
        self,
        sections: Dict[str, PromptSection],
        budget: int,
    ) -> Dict[str, PromptSection]:
        """Apply compression strategies to fit within budget.

        Strategies:
        1. Remove duplicate content across sections
        2. Compress import blocks
        3. Truncate long code blocks while keeping signatures
        4. Summarize repetitive patterns
        """
        if not sections:
            return sections

        compressed = {}

        seen_hashes: Set[str] = set()

        for name, section in sections.items():
            if name == "system_instructions":
                compressed[name] = section
                continue

            content = section.content
            content_hash = hashlib.md5(content.encode()).hexdigest()

            if content_hash in seen_hashes:
                logger.debug(f"Skipping duplicate section: {name}")
                continue

            seen_hashes.add(content_hash)

            content = self._compress_imports(content)
            content = self._compress_code_blocks(content)
            content = self._remove_empty_lines(content)

            new_tokens = estimate_tokens(content)
            if new_tokens < section.token_count:
                section = PromptSection(
                    name=section.name,
                    content=content,
                    token_count=new_tokens,
                    version=section.version,
                    priority=section.priority,
                    compressed=True,
                    source_files=section.source_files,
                )

            compressed[name] = section

        return compressed

    def _compress_imports(self, content: str) -> str:
        """Compress import blocks to only relevant imports."""
        lines = content.split("\n")
        result = []
        import_lines = []
        in_import_block = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith(("import ", "from ", "require(")):
                import_lines.append(line)
                in_import_block = True
            else:
                if in_import_block and import_lines:
                    if len(import_lines) > 5:
                        result.append(f"# {len(import_lines)} import statements (compressed)")
                    else:
                        result.extend(import_lines)
                    import_lines = []
                    in_import_block = False
                result.append(line)

        if in_import_block and import_lines:
            if len(import_lines) > 5:
                result.append(f"# {len(import_lines)} import statements (compressed)")
            else:
                result.extend(import_lines)

        return "\n".join(result)

    def _compress_code_blocks(self, content: str) -> str:
        """Compress long code blocks by keeping signatures and removing bodies."""
        lines = content.split("\n")
        result = []
        in_code_block = False
        code_lines = []
        code_indent = 0

        for line in lines:
            if line.strip().startswith("```"):
                if in_code_block:
                    if len(code_lines) > 30:
                        kept = code_lines[:15] + [f"    # ... {len(code_lines) - 30} lines compressed ..."] + code_lines[-15:]
                        result.extend(kept)
                    else:
                        result.extend(code_lines)
                    result.append(line)
                    in_code_block = False
                    code_lines = []
                else:
                    result.append(line)
                    in_code_block = True
            elif in_code_block:
                code_lines.append(line)
            else:
                result.append(line)

        if in_code_block and code_lines:
            result.extend(code_lines)

        return "\n".join(result)

    def _remove_empty_lines(self, content: str) -> str:
        """Remove excessive empty lines."""
        lines = content.split("\n")
        result = []
        empty_count = 0

        for line in lines:
            if line.strip() == "":
                empty_count += 1
                if empty_count <= 2:
                    result.append(line)
            else:
                empty_count = 0
                result.append(line)

        return "\n".join(result)
