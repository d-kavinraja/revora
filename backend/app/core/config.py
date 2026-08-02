"""Application configuration.

All secrets are required via environment variables.
No hardcoded defaults for security-sensitive values.
"""

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # App Settings
    APP_NAME: str = "Revora"
    APP_ENV: str = "development"

    # CORS
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:3002",
        "http://127.0.0.1:3002",
    ]

    # Security - REQUIRED, no defaults for secrets
    SECRET_KEY: str = Field(
        ...,
        description='Application secret key. Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"',
    )
    JWT_SECRET_KEY: str = Field(
        ...,
        description='JWT signing key. Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"',
    )
    ENCRYPTION_KEY: str = Field(
        ...,
        description='Fernet encryption key. Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"',
    )

    # Database - REQUIRED
    DATABASE_URL: str = Field(..., description="PostgreSQL async connection string")

    # Security
    ALLOW_HTTP_SELF_HOSTED: bool = Field(
        default=False,
        description="Allow HTTP for self-hosted providers like Ollama. Set to true only for local development.",
    )

    # Redis (optional)
    REDIS_URL: str | None = Field(
        default=None, description="Redis connection string for caching and queues"
    )

    # GitHub OAuth - REQUIRED for login
    GITHUB_CLIENT_ID: str | None = Field(
        default=None, description="GitHub OAuth App Client ID"
    )
    GITHUB_CLIENT_SECRET: str | None = Field(
        default=None, description="GitHub OAuth App Client Secret"
    )

    # GitHub App - REQUIRED for repository access
    GITHUB_APP_ID: str | None = Field(default=None, description="GitHub App ID")
    GITHUB_APP_PRIVATE_KEY: str | None = Field(
        default=None, description="GitHub App private key (PEM format)"
    )
    GITHUB_WEBHOOK_SECRET: str = Field(
        default="dev_webhook_secret",
        description="GitHub webhook signature verification secret",
    )

    # Usage & Analytics
    # Temporarily disabled while redesigning model-level pricing.
    # When False: recording is skipped, API returns disabled response.
    USAGE_ANALYTICS_ENABLED: bool = Field(
        default=False,
        description="Master flag for usage tracking and analytics subsystem",
    )

    # Rate Limiting
    RATE_LIMIT_LOGIN: int = Field(default=5, description="Login attempts per minute")
    RATE_LIMIT_REGISTER: int = Field(
        default=3, description="Registration attempts per minute"
    )

    # JWT
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=1440, description="JWT token expiry in minutes"  # 1 day
    )

    # Real-time / background sync
    PR_STATE_SYNC_INTERVAL_MINUTES: int = Field(
        default=3,
        description="DEPRECATED — alias for SYNC_RECOVERY_INTERVAL_MINUTES (kept for back-compat)",
    )
    # Tier 1: repos with open PRs / new repos — every N minutes.
    SYNC_RECOVERY_INTERVAL_MINUTES: int = Field(
        default=3,
        description="Minutes between background sync passes for active repos (0 disables)",
    )
    # Tier 2: repos updated in the last SYNC_TIER2_ACTIVE_DAYS days.
    SYNC_TIER2_INTERVAL_MINUTES: int = Field(
        default=15,
        description="Minutes between sync passes for recently-updated repos (0 disables)",
    )
    # Tier 3: everything else.
    SYNC_TIER3_INTERVAL_MINUTES: int = Field(
        default=60,
        description="Minutes between sync passes for remaining repos (0 disables)",
    )
    SYNC_TIER2_ACTIVE_DAYS: int = Field(
        default=7,
        description="A repo counts as 'recently updated' if synced within this many days",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_secrets(self) -> "Settings":
        # Ensure a real webhook secret is set in production
        if self.APP_ENV not in ("development", "testing"):
            if self.GITHUB_WEBHOOK_SECRET == "dev_webhook_secret":
                raise ValueError("GITHUB_WEBHOOK_SECRET must be set in non-development environments.")
        return self


settings = Settings()
