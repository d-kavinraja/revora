"""Duplicate code detection engine.

Detects potential copy-paste code using content hashing.
Uses deterministic analysis without LLM calls.
"""

import hashlib
from typing import Dict, List

from app.intelligence.base_detector import BaseDetector, DetectorResult
from app.core.constants import MAX_FILES_PER_DETECTOR


# File extensions to analyze
CODE_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".java", ".rb"}

# Minimum lines for duplicate detection
MIN_LINES = 5


class DuplicateDetector(BaseDetector):
    """Detects potential duplicate code blocks."""

    @property
    def name(self) -> str:
        return "duplicate_detector"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def detect(self, walker: 'RepoWalker') -> DetectorResult:
        """Detect duplicate code using the RepoWalker cache.

        Args:
            walker: Initialized RepoWalker.

        Returns:
            DetectorResult with duplicate code findings.
        """
        # Map from content hash to file locations
        content_hashes: Dict[str, List[Dict]] = {}
        files_analyzed = 0

        # Collect code files
        code_files = [
            fp for fp in walker.file_paths
            if any(fp.endswith(ext) for ext in CODE_EXTENSIONS)
        ]

        for fp in code_files[:MAX_FILES_PER_DETECTOR]:
            content = await walker.get_content(fp, max_chars=20000)
            if not content:
                continue

            files_analyzed += 1

            # Split into blocks of MIN_LINES
            lines = content.split("\n")
            for i in range(0, len(lines) - MIN_LINES, MIN_LINES):
                block = "\n".join(lines[i:i + MIN_LINES]).strip()

                # Skip empty or very short blocks
                if len(block) < 50:
                    continue

                # Skip common patterns (imports, comments, blank lines)
                if block.startswith("#") or block.startswith("//"):
                    continue

                # Hash the block
                block_hash = hashlib.md5(block.encode()).hexdigest()

                if block_hash not in content_hashes:
                    content_hashes[block_hash] = []

                content_hashes[block_hash].append({
                    "file": fp,
                    "line_start": i + 1,
                    "line_end": i + MIN_LINES,
                    "preview": block[:100],
                })

        # Find duplicates (hashes with multiple locations)
        duplicates: List[Dict] = []
        for block_hash, locations in content_hashes.items():
            if len(locations) > 1:
                # Deduplicate by file
                files = set(loc["file"] for loc in locations)
                if len(files) > 1:  # Only report if in different files
                    duplicates.append({
                        "locations": locations,
                        "occurrences": len(locations),
                        "files": list(files),
                    })

        # Sort by number of occurrences
        duplicates.sort(key=lambda x: x["occurrences"], reverse=True)

        return DetectorResult(
            success=True,
            data={
                "files_analyzed": files_analyzed,
                "duplicates": duplicates[:20],  # Top 20
                "duplicates_count": len(duplicates),
                "total_duplicate_locations": sum(d["occurrences"] for d in duplicates),
            },
            confidence=0.6,  # Medium confidence - this is heuristic
        )
