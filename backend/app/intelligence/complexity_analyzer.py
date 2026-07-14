"""Complexity analysis engine.

Analyzes cyclomatic complexity of code files using pattern matching.
Uses deterministic analysis without LLM calls.
"""

import re
from typing import Dict, List

from app.intelligence.base_detector import BaseDetector, DetectorResult
from app.core.constants import MAX_FILES_PER_DETECTOR


# Complexity-increasing keywords by language
COMPLEXITY_KEYWORDS = {
    "python": ["if ", "elif ", "else:", "for ", "while ", "try:", "except", "with ", "and ", "or ", "lambda "],
    "javascript": ["if ", "else ", "for ", "while ", "switch ", "case ", "catch ", "&&", "||", "?.", "??"],
    "typescript": ["if ", "else ", "for ", "while ", "switch ", "case ", "catch ", "&&", "||", "?.", "??"],
    "go": ["if ", "else ", "for ", "switch ", "select ", "case ", "||", "&&"],
    "java": ["if ", "else ", "for ", "while ", "switch ", "case ", "catch ", "&&", "||", "?:"],
    "rust": ["if ", "else ", "for ", "while ", "match ", "loop ", "&&", "||", "?"],
    "ruby": ["if ", "elsif ", "else ", "unless ", "while ", "until ", "for ", "case ", "when ", "&&", "||", "and ", "or "],
}

# File extensions to analyze
COMPLEXITY_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".java", ".rb", ".rs"}


class ComplexityAnalyzer(BaseDetector):
    """Analyzes code complexity using pattern matching."""

    @property
    def name(self) -> str:
        return "complexity_analyzer"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def detect(self, walker: 'RepoWalker') -> DetectorResult:
        """Analyze code complexity using the RepoWalker cache.

        Args:
            walker: Initialized RepoWalker.

        Returns:
            DetectorResult with complexity metrics.
        """
        file_complexities: List[Dict] = []
        total_complexity = 0
        files_analyzed = 0

        # Collect code files
        code_files = [
            fp for fp in walker.file_paths
            if any(fp.endswith(ext) for ext in COMPLEXITY_EXTENSIONS)
        ]

        for fp in code_files[:MAX_FILES_PER_DETECTOR]:
            content = await walker.get_content(fp, max_chars=10000)
            if not content:
                continue

            files_analyzed += 1

            # Determine language
            language = self._detect_language(fp)
            keywords = COMPLEXITY_KEYWORDS.get(language, COMPLEXITY_KEYWORDS["python"])

            # Count complexity keywords
            complexity = 1  # Base complexity
            for keyword in keywords:
                complexity += content.count(keyword)

            # Count functions/methods (rough estimate)
            func_count = len(re.findall(r"def \w+|function \w+|func \w+|fn \w+", content))

            total_complexity += complexity

            if complexity > 10:  # Only report files with meaningful complexity
                file_complexities.append({
                    "file": fp,
                    "complexity": complexity,
                    "functions": func_count,
                    "language": language,
                })

        # Sort by complexity descending
        file_complexities.sort(key=lambda x: x["complexity"], reverse=True)

        # Calculate average complexity
        avg_complexity = total_complexity / files_analyzed if files_analyzed > 0 else 0

        return DetectorResult(
            success=True,
            data={
                "files_analyzed": files_analyzed,
                "total_complexity": total_complexity,
                "average_complexity": round(avg_complexity, 2),
                "high_complexity_files": file_complexities[:20],  # Top 20
                "high_complexity_count": len(file_complexities),
            },
            confidence=0.7,
        )

    def _detect_language(self, file_path: str) -> str:
        """Detect programming language from file extension."""
        if file_path.endswith(".py"):
            return "python"
        elif file_path.endswith((".js", ".jsx", ".mjs")):
            return "javascript"
        elif file_path.endswith((".ts", ".tsx")):
            return "typescript"
        elif file_path.endswith(".go"):
            return "go"
        elif file_path.endswith(".java"):
            return "java"
        elif file_path.endswith(".rs"):
            return "rust"
        elif file_path.endswith(".rb"):
            return "ruby"
        return "python"  # Default
