"""Cloud provider detection engine.

Detects cloud providers by analyzing configuration files and code content.
Uses the shared RepoWalker for efficient filesystem access.
"""

from typing import List

from app.intelligence.base_detector import BaseDetector, DetectorResult
from app.core.constants import MAX_FILES_PER_DETECTOR


CLOUD_INDICATORS = {
    "aws": ["AWS", "aws", "boto3", "lambda", "dynamodb", "s3", "sqs", "sns"],
    "gcp": ["GCP", "gcp", "google-cloud", "firebase", "bigquery", "pubsub"],
    "azure": ["Azure", "azure", "azure-storage", "cosmosdb", "azure-functions"],
    "vercel": ["vercel", "Vercel", "next.config"],
    "netlify": ["netlify", "Netlify", "netlify.toml"],
    "heroku": ["heroku", "Heroku", "Procfile"],
    "digitalocean": ["digitalocean", "DigitalOcean"],
    "cloudflare": ["cloudflare", "Cloudflare", "workers"],
}


class CloudDetector(BaseDetector):
    """Detects cloud providers."""

    @property
    def name(self) -> str:
        return "cloud_detector"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def detect(self, walker: 'RepoWalker') -> DetectorResult:
        """Detect cloud providers using the RepoWalker cache.

        Args:
            walker: Initialized RepoWalker.

        Returns:
            DetectorResult with cloud provider info.
        """
        found_providers = []

        # Check config files for cloud indicators
        config_files = [
            fp for fp in walker.file_paths
            if any(fp.endswith(ext) for ext in [
                ".py", ".js", ".ts", ".tsx", ".jsx",
                ".go", ".java", ".rb", ".php",
                ".yaml", ".yml", ".json", ".toml",
                ".env", ".cfg", ".ini", ".tf", ".hcl",
            ])
        ]

        files_checked = 0
        all_content = ""

        for fp in config_files:
            if files_checked >= MAX_FILES_PER_DETECTOR:
                break

            content = await walker.get_content(fp, max_chars=2000)
            if content:
                all_content += content + "\n"
                files_checked += 1

        # Check for cloud provider indicators
        for provider, indicators in CLOUD_INDICATORS.items():
            for indicator in indicators:
                if indicator in all_content:
                    if provider not in found_providers:
                        found_providers.append(provider)
                    break

        return DetectorResult(
            success=True,
            data={
                "provider": found_providers[0] if found_providers else "",
                "providers": found_providers,
            },
            confidence=0.8 if found_providers else 0.0,
        )


# Legacy function interface for backward compatibility
def detect_cloud_provider(repo_path: str) -> str:
    """Detect cloud provider in a repository (legacy interface)."""
    import asyncio
    from app.intelligence.repo_walker import RepoWalker

    async def _detect():
        walker = RepoWalker(repo_path)
        await walker.walk()
        detector = CloudDetector()
        result = await detector.detect(walker)
        return result.data.get("provider", "")

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, _detect()).result()
        else:
            return loop.run_until_complete(_detect())
    except RuntimeError:
        return asyncio.run(_detect())
