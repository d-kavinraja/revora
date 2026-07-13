import logging
from typing import Optional, List

from app.github_review.models import GitHubReviewComment, GitHubReviewSummary
from app.verification.models import VerificationResult

logger = logging.getLogger(__name__)

SEVERITY_EMOJI = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🔵",
}

ISSUE_TYPE_EMOJI = {
    "bug": "🐛",
    "security": "🔒",
    "performance": "⚡",
    "style": "🎨",
    "improvement": "💡",
}


class GitHubReviewGenerator:
    """Converts verified findings to GitHub PR review format."""

    async def generate(
        self,
        verified: VerificationResult,
        pr_title: str = "",
        repo_summary: str = "",
        usage_stats: Optional[dict] = None,
        duration_ms: float = 0,
    ) -> GitHubReviewSummary:
        risk_score = self._calculate_risk_score(verified)
        summary_body = self._build_summary(verified, risk_score, pr_title, usage_stats, duration_ms)
        comments = self._build_comments(verified)

        event = "COMMENT"
        if risk_score == "critical":
            event = "REQUEST_CHANGES"
        elif risk_score == "high":
            event = "REQUEST_CHANGES"

        if not verified.findings and verified.total_findings == 0:
            event = "APPROVE"

        return GitHubReviewSummary(
            body=summary_body,
            event=event,
            risk_score=risk_score,
            comments=comments,
            stats={
                "total_findings": verified.total_findings,
                "verified_count": verified.verified_count,
                "rejected_count": verified.rejected_count,
                "avg_confidence": round(verified.avg_confidence, 2),
            },
        )

    def _calculate_risk_score(self, verified: VerificationResult) -> str:
        if not verified.findings:
            return "low"

        critical = sum(1 for f in verified.findings if f.severity == "critical")
        high = sum(1 for f in verified.findings if f.severity == "high")

        if critical > 0:
            return "critical"
        if high >= 2:
            return "high"
        if high > 0 or len(verified.findings) >= 5:
            return "medium"
        return "low"

    def _build_summary(
        self,
        verified: VerificationResult,
        risk_score: str,
        pr_title: str,
        usage_stats: Optional[dict],
        duration_ms: float,
    ) -> str:
        sections = []

        # Risk header
        risk_emoji = {"low": "✅", "medium": "⚠️", "high": "🔶", "critical": "🔴"}
        sections.append(f"## Revora AI Review\n")
        sections.append(f"**Risk Assessment: {risk_emoji.get(risk_score, '❓')} {risk_score.upper()}**\n")

        # Summary
        if not verified.findings:
            sections.append("### Summary\n")
            sections.append("No significant issues found. The code looks good! ✅\n")
        else:
            sections.append("### Summary\n")
            sections.append(f"Found **{len(verified.findings)}** verified issues across the changed files.\n")

            # Group by type
            by_type = {}
            for f in verified.findings:
                by_type.setdefault(f.issue_type, []).append(f)

            for issue_type, findings in by_type.items():
                emoji = ISSUE_TYPE_EMOJI.get(issue_type, "•")
                sections.append(f"### {emoji} {issue_type.title()} Findings\n")
                for finding in findings:
                    sev = SEVERITY_EMOJI.get(finding.severity, "•")
                    loc = f"`{finding.file_path}`"
                    if finding.line_number:
                        loc += f" line {finding.line_number}"
                    sections.append(f"- {sev} **[{finding.severity.upper()}]** {loc}")
                    sections.append(f"  {finding.description[:200]}")
                    if finding.suggestion:
                        sections.append(f"  > 💡 Suggestion: {finding.suggestion[:200]}")
                    sections.append("")

        # Positive feedback
        sections.append("### Positive Feedback\n")
        if verified.verified_count == 0 and verified.total_findings == 0:
            sections.append("The code follows good practices. No issues detected.\n")
        else:
            sections.append("Code structure and organization look solid.\n")

        # Footer
        sections.append("---")
        footer_parts = []
        if usage_stats:
            footer_parts.append(f"*Tokens: {usage_stats.get('input_tokens', 0)} in / {usage_stats.get('output_tokens', 0)} out*")
            if usage_stats.get("total_cost_usd", 0) > 0:
                footer_parts.append(f"*Cost: ${usage_stats['total_cost_usd']:.4f}*")
        if duration_ms > 0:
            footer_parts.append(f"*Duration: {duration_ms/1000:.1f}s*")
        if footer_parts:
            sections.append(" | ".join(footer_parts))
        sections.append("*Reviewed by Revora AI*")

        return "\n".join(sections)

    def _build_comments(self, verified: VerificationResult) -> List[GitHubReviewComment]:
        comments = []
        for finding in verified.findings:
            body_parts = []
            sev = SEVERITY_EMOJI.get(finding.severity, "•")
            body_parts.append(f"{sev} **{finding.severity.upper()}** — {finding.description[:300]}")
            if finding.suggestion:
                body_parts.append(f"\n> 💡 **Suggestion:** {finding.suggestion[:200]}")

            comments.append(GitHubReviewComment(
                path=finding.file_path,
                body="\n".join(body_parts),
                line=finding.line_number,
            ))

        return comments


github_review_generator = GitHubReviewGenerator()
