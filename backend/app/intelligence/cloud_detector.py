import os
from typing import Optional


CLOUD_INDICATORS = {
    "aws": ["aws-sdk", "boto3", "AWS_", "lambda", "cloudformation", "sam", "cdk"],
    "gcp": ["google-cloud", "firebase", "GCP_", "cloud run", "cloud functions"],
    "azure": ["azure-", "Azure", "AZURE_", "azure-functions"],
    "vercel": ["vercel.json", "@vercel/", "VERCEL_"],
    "netlify": ["netlify.toml", "netlify/", "NETLIFY_"],
    "cloudflare": ["wrangler.toml", "cloudflare", "CLOUDFLARE_"],
    "heroku": ["Procfile", "heroku"],
    "docker": ["Dockerfile", "docker-compose"],
}


def detect_cloud_provider(repo_path: str) -> Optional[str]:
    config_files = {
        "vercel": ["vercel.json", ".vercelignore"],
        "netlify": ["netlify.toml", "_redirects"],
        "cloudflare": ["wrangler.toml"],
        "heroku": ["Procfile"],
        "docker": ["Dockerfile", "docker-compose.yml", "docker-compose.yaml"],
    }

    for provider, files in config_files.items():
        for f in files:
            if os.path.exists(os.path.join(repo_path, f)):
                return provider

    indicators_content = ""
    count = 0
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "venv"}]
        for f in files:
            if f.endswith((".py", ".js", ".ts", ".json", ".yaml", ".yml", ".toml")):
                try:
                    with open(os.path.join(root, f), "r", encoding="utf-8", errors="ignore") as fh:
                        indicators_content += fh.read()[:2000] + "\n"
                except (OSError, IOError):
                    pass
                count += 1
                if count > 50:
                    break
        if count > 50:
            break

    for provider, keywords in CLOUD_INDICATORS.items():
        if provider in ("vercel", "netlify", "cloudflare", "heroku", "docker"):
            continue
        for kw in keywords:
            if kw in indicators_content:
                return provider

    return None
