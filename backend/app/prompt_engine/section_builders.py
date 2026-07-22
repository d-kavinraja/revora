"""Section builders for prompt construction.

Each builder produces one of the 14 prompt sections following the ABC pattern
with safe_* wrappers for error isolation.
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict

from app.prompt_engine.models import (
    PromptSection, PromptBuildRequest, ReviewType, TokenMetadata
)
from app.prompt_engine.review_types import get_review_config

logger = logging.getLogger(__name__)

CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Rough token estimation: 4 chars per token."""
    return len(text) // CHARS_PER_TOKEN


class BaseSectionBuilder(ABC):
    """Abstract base for all section builders with error isolation."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Section name identifier."""

    @property
    @abstractmethod
    def priority(self) -> int:
        """Priority for ordering (higher = included first when budget is tight)."""

    @abstractmethod
    async def build(self, request: PromptBuildRequest, context: dict) -> Optional[PromptSection]:
        """Build the section content."""

    async def safe_build(self, request: PromptBuildRequest, context: dict) -> Optional[PromptSection]:
        """Build with error isolation. Returns None on failure instead of raising."""
        try:
            section = await self.build(request, context)
            if section:
                section.token_count = estimate_tokens(section.content)
                section.priority = self.priority
            return section
        except Exception as e:
            logger.warning(f"Section builder {self.name} failed: {e}")
            return None


class SystemInstructionsBuilder(BaseSectionBuilder):
    """Builds the system instructions section based on review type."""

    @property
    def name(self) -> str:
        return "system_instructions"

    @property
    def priority(self) -> int:
        return 100

    async def build(self, request: PromptBuildRequest, context: dict) -> Optional[PromptSection]:
        config = get_review_config(request.review_type)
        return PromptSection(
            name=self.name,
            content=config["system_instruction"],
        )


class RepositorySummaryBuilder(BaseSectionBuilder):
    """Builds the repository summary section from intelligence data."""

    @property
    def name(self) -> str:
        return "repository_summary"

    @property
    def priority(self) -> int:
        return 90

    async def build(self, request: PromptBuildRequest, context: dict) -> Optional[PromptSection]:
        if not request.intelligence_data:
            return None

        data = request.intelligence_data
        parts = []

        if "languages" in data:
            langs = data["languages"]
            if isinstance(langs, list):
                lang_names = [l.get("name", str(l)) if isinstance(l, dict) else str(l) for l in langs]
                parts.append(f"**Languages**: {', '.join(lang_names)}")
            elif isinstance(langs, dict):
                parts.append(f"**Languages**: {', '.join(langs.keys())}")

        if "frameworks" in data:
            fws = data["frameworks"]
            if isinstance(fws, list):
                fw_names = [f.get("name", str(f)) if isinstance(f, dict) else str(f) for f in fws]
                parts.append(f"**Frameworks**: {', '.join(fw_names)}")

        if "file_count" in data:
            parts.append(f"**Files**: {data['file_count']}")

        if "total_lines" in data:
            parts.append(f"**Lines of Code**: {data['total_lines']}")

        content = "\n".join(parts) if parts else str(data)
        return PromptSection(name=self.name, content=content)


class ArchitectureSummaryBuilder(BaseSectionBuilder):
    """Builds the architecture summary section from intelligence data."""

    @property
    def name(self) -> str:
        return "architecture_summary"

    @property
    def priority(self) -> int:
        return 85

    async def build(self, request: PromptBuildRequest, context: dict) -> Optional[PromptSection]:
        if not request.intelligence_data:
            return None

        arch = request.intelligence_data.get("architecture", {})
        if not arch:
            return None

        parts = []
        if isinstance(arch, dict):
            if "pattern" in arch:
                parts.append(f"**Pattern**: {arch['pattern']}")
            if "description" in arch:
                parts.append(f"**Description**: {arch['description']}")
            if "strengths" in arch and arch["strengths"]:
                parts.append(f"**Strengths**: {', '.join(arch['strengths']) if isinstance(arch['strengths'], list) else arch['strengths']}")
            if "weaknesses" in arch and arch["weaknesses"]:
                parts.append(f"**Weaknesses**: {', '.join(arch['weaknesses']) if isinstance(arch['weaknesses'], list) else arch['weaknesses']}")
        else:
            parts.append(str(arch))

        content = "\n".join(parts) if parts else "No architecture information available."
        return PromptSection(name=self.name, content=content)


class RepositoryRulesBuilder(BaseSectionBuilder):
    """Builds the repository rules section."""

    @property
    def name(self) -> str:
        return "repository_rules"

    @property
    def priority(self) -> int:
        return 80

    async def build(self, request: PromptBuildRequest, context: dict) -> Optional[PromptSection]:
        all_rules = list(request.rules) if request.rules else []

        ranked = context.get("ranked_context")
        if ranked and hasattr(ranked, "rule_context") and ranked.rule_context:
            for rc in ranked.rule_context:
                if rc.content and rc.content not in all_rules:
                    all_rules.append(rc.content)

        if not all_rules:
            return None

        rules_text = "\n".join(f"- {r}" for r in all_rules)
        return PromptSection(name=self.name, content=rules_text)


class CodingConventionsBuilder(BaseSectionBuilder):
    """Builds the coding conventions section."""

    @property
    def name(self) -> str:
        return "coding_conventions"

    @property
    def priority(self) -> int:
        return 75

    async def build(self, request: PromptBuildRequest, context: dict) -> Optional[PromptSection]:
        if not request.conventions:
            return None
        return PromptSection(name=self.name, content=request.conventions)


class OrganizationRulesBuilder(BaseSectionBuilder):
    """Builds the organization rules section."""

    @property
    def name(self) -> str:
        return "organization_rules"

    @property
    def priority(self) -> int:
        return 70

    async def build(self, request: PromptBuildRequest, context: dict) -> Optional[PromptSection]:
        if not request.organization_rules:
            return None
        rules_text = "\n".join(f"- {r}" for r in request.organization_rules)
        return PromptSection(name=self.name, content=rules_text)


class RelevantFilesBuilder(BaseSectionBuilder):
    """Builds the relevant files section from ranked context."""

    @property
    def name(self) -> str:
        return "relevant_files"

    @property
    def priority(self) -> int:
        return 60

    async def build(self, request: PromptBuildRequest, context: dict) -> Optional[PromptSection]:
        ranked = context.get("ranked_context")
        if not ranked:
            return None

        files = []
        for ctx in ranked.rankable_contexts[:20]:
            files.append(f"- `{ctx.file_path}` (relevance: {ctx.relevance_score:.2f}, source: {ctx.source})")

        if not files:
            return None

        content = "The following files are relevant to this review:\n\n" + "\n".join(files)
        return PromptSection(name=self.name, content=content)


class RelevantCodeBuilder(BaseSectionBuilder):
    """Builds the relevant code section with actual file contents."""

    @property
    def name(self) -> str:
        return "relevant_code"

    @property
    def priority(self) -> int:
        return 55

    async def build(self, request: PromptBuildRequest, context: dict) -> Optional[PromptSection]:
        ranked = context.get("ranked_context")
        if not ranked:
            return None

        code_blocks = []
        for ctx in ranked.rankable_contexts[:10]:
            if ctx.content:
                truncated = ctx.content[:1500]
                if len(ctx.content) > 1500:
                    truncated += "\n... (truncated)"
                code_blocks.append(f"### {ctx.file_path}\n```{self._detect_language(ctx.file_path)}\n{truncated}\n```")

        if not code_blocks:
            return None

        content = "\n\n".join(code_blocks)
        return PromptSection(name=self.name, content=content)

    def _detect_language(self, file_path: str) -> str:
        # Order matters: more specific extensions must come before less specific ones
        # e.g., .tsx before .ts, .jsx before .js, .hpp before .h
        ext_map = {
            ".py": "python", ".java": "java", ".go": "go",
            ".rs": "rust", ".rb": "ruby", ".php": "php", ".cs": "csharp",
            ".cpp": "cpp", ".hpp": "cpp",
            ".sql": "sql", ".sh": "bash", ".yaml": "yaml", ".yml": "yaml",
            ".json": "json", ".xml": "xml", ".html": "html", ".css": "css",
            # .tsx/.jsx BEFORE .ts/.js to match correctly
            ".tsx": "tsx", ".jsx": "jsx",
            ".ts": "typescript", ".js": "javascript",
            ".c": "c", ".h": "c",
        }
        for ext, lang in ext_map.items():
            if file_path.endswith(ext):
                return lang
        return ""


class StaticAnalysisBuilder(BaseSectionBuilder):
    """Builds the static analysis results section."""

    @property
    def name(self) -> str:
        return "static_analysis"

    @property
    def priority(self) -> int:
        return 50

    async def build(self, request: PromptBuildRequest, context: dict) -> Optional[PromptSection]:
        if not request.static_analysis:
            return None
        return PromptSection(name=self.name, content=request.static_analysis)


class ReviewContextBuilder(BaseSectionBuilder):
    """Builds the review context section with PR metadata."""

    @property
    def name(self) -> str:
        return "review_context"

    @property
    def priority(self) -> int:
        return 45

    async def build(self, request: PromptBuildRequest, context: dict) -> Optional[PromptSection]:
        parts = []

        if request.pr_number:
            parts.append(f"**PR Number**: #{request.pr_number}")
        if request.pr_title:
            parts.append(f"**PR Title**: {request.pr_title}")
        if request.pr_description:
            desc = request.pr_description[:1000]
            parts.append(f"**PR Description**: {desc}")

        if request.review_type == ReviewType.REPOSITORY_CHAT:
            parts.append("**Context**: Repository-wide analysis")
        elif request.review_type == ReviewType.REPO_REVIEW:
            parts.append("**Context**: Full repository review")

        # Include the actual code diff for the LLM to review
        if request.diff_content:
            diff = request.diff_content
            if len(diff) > 50000:
                diff = diff[:50000] + "\n\n... (diff truncated, too large)"
            parts.append(f"**Code Diff**:\n```diff\n{diff}\n```")


        if not parts:
            return None

        content = "\n".join(parts)
        return PromptSection(name=self.name, content=content)


class IssueContextBuilder(BaseSectionBuilder):
    """Builds the issue context section."""

    @property
    def name(self) -> str:
        return "issue_context"

    @property
    def priority(self) -> int:
        return 40

    async def build(self, request: PromptBuildRequest, context: dict) -> Optional[PromptSection]:
        if not request.issue_context:
            return None
        return PromptSection(name=self.name, content=request.issue_context)


class OutputFormatBuilder(BaseSectionBuilder):
    """Builds the output format section based on review type."""

    @property
    def name(self) -> str:
        return "output_format"

    @property
    def priority(self) -> int:
        return 30

    async def build(self, request: PromptBuildRequest, context: dict) -> Optional[PromptSection]:
        config = get_review_config(request.review_type)
        return PromptSection(name=self.name, content=config["output_format"])


class TokenMetadataBuilder(BaseSectionBuilder):
    """Builds the token metadata section (internal, not exposed to user)."""

    @property
    def name(self) -> str:
        return "token_metadata"

    @property
    def priority(self) -> int:
        return 5

    async def build(self, request: PromptBuildRequest, context: dict) -> Optional[PromptSection]:
        token_meta = context.get("token_metadata")
        if not token_meta:
            token_meta = TokenMetadata(budget_limit=request.token_budget)

        content = f"""Token Budget: {token_meta.budget_limit} tokens
Budget Used: {token_meta.budget_used:.1%}
Compression Ratio: {token_meta.compression_ratio:.2f}"""
        return PromptSection(name=self.name, content=content)


class ProviderMetadataBuilder(BaseSectionBuilder):
    """Builds the provider metadata section (internal)."""

    @property
    def name(self) -> str:
        return "provider_metadata"

    @property
    def priority(self) -> int:
        return 5

    async def build(self, request: PromptBuildRequest, context: dict) -> Optional[PromptSection]:
        content = f"Provider: {request.provider}"
        if request.model:
            content += f"\nModel: {request.model}"
        return PromptSection(name=self.name, content=content)


# All section builders in priority order
ALL_SECTION_BUILDERS = [
    SystemInstructionsBuilder(),
    RepositorySummaryBuilder(),
    ArchitectureSummaryBuilder(),
    RepositoryRulesBuilder(),
    CodingConventionsBuilder(),
    OrganizationRulesBuilder(),
    RelevantFilesBuilder(),
    RelevantCodeBuilder(),
    StaticAnalysisBuilder(),
    ReviewContextBuilder(),
    IssueContextBuilder(),
    OutputFormatBuilder(),
    TokenMetadataBuilder(),
    ProviderMetadataBuilder(),
]


