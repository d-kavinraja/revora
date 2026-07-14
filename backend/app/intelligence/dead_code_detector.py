"""Dead code detection engine.

Detects potentially unused functions, classes, and imports.
Uses deterministic analysis without LLM calls.
"""

import re
from typing import Dict, List, Set

from app.intelligence.base_detector import BaseDetector, DetectorResult
from app.core.constants import MAX_FILES_PER_DETECTOR


# File extensions to analyze
CODE_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx"}


class DeadCodeDetector(BaseDetector):
    """Detects potentially unused code."""

    @property
    def name(self) -> str:
        return "dead_code_detector"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def detect(self, walker: 'RepoWalker') -> DetectorResult:
        """Detect dead code using the RepoWalker cache.

        Args:
            walker: Initialized RepoWalker.

        Returns:
            DetectorResult with dead code findings.
        """
        unused_imports: List[Dict] = []
        unused_functions: List[Dict] = []
        files_analyzed = 0

        # Collect code files
        code_files = [
            fp for fp in walker.file_paths
            if any(fp.endswith(ext) for ext in CODE_EXTENSIONS)
        ]

        # Build a set of all function/class definitions and their references
        all_definitions: Dict[str, List[Dict]] = {}
        all_references: Set[str] = set()

        for fp in code_files[:MAX_FILES_PER_DETECTOR]:
            content = await walker.get_content(fp, max_chars=10000)
            if not content:
                continue

            files_analyzed += 1

            # Extract Python definitions
            if fp.endswith(".py"):
                # Find function definitions
                for match in re.finditer(r"def (\w+)\(", content):
                    name = match.group(1)
                    if name.startswith("_") and not name.startswith("__"):
                        line_num = content[:match.start()].count("\n") + 1
                        if name not in all_definitions:
                            all_definitions[name] = []
                        all_definitions[name].append({
                            "file": fp,
                            "line": line_num,
                            "type": "function",
                        })

                # Find class definitions
                for match in re.finditer(r"class (\w+)", content):
                    name = match.group(1)
                    line_num = content[:match.start()].count("\n") + 1
                    if name not in all_definitions:
                        all_definitions[name] = []
                    all_definitions[name].append({
                        "file": fp,
                        "line": line_num,
                        "type": "class",
                    })

                # Find imports
                for match in re.finditer(r"from \w+ import (\w+)", content):
                    name = match.group(1)
                    line_num = content[:match.start()].count("\n") + 1
                    unused_imports.append({
                        "file": fp,
                        "line": line_num,
                        "name": name,
                        "type": "import",
                    })

            # Collect all identifiers used in the file (rough estimate)
            identifiers = set(re.findall(r"\b([a-zA-Z_]\w+)\b", content))
            all_references.update(identifiers)

        # Find unused definitions (private functions that are never referenced)
        for name, defs in all_definitions.items():
            if name.startswith("_") and not name.startswith("__"):
                # Check if the name appears anywhere else
                if name not in all_references or len(defs) == 1:
                    for defn in defs:
                        unused_functions.append({
                            "file": defn["file"],
                            "line": defn["line"],
                            "name": name,
                            "type": defn["type"],
                        })

        return DetectorResult(
            success=True,
            data={
                "files_analyzed": files_analyzed,
                "unused_imports": unused_imports[:50],  # Limit output
                "unused_functions": unused_functions[:50],
                "unused_imports_count": len(unused_imports),
                "unused_functions_count": len(unused_functions),
            },
            confidence=0.5,  # Low confidence - this is heuristic
        )
