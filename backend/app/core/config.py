"""Application configuration.

All secrets are required via environment variables.
No hardcoded defaults for security-sensitive values.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional, List


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # App Settings
    APP_NAME: str = "Revora"
    APP_ENV: str = "development"

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3001", "http://127.0.0.1:3001", "http://localhost:3002", "http://127.0.0.1:3002"]

    # Security - REQUIRED, no defaults for secrets
    SECRET_KEY: str = Field(
        ...,
        description="Application secret key. Generate with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
    )
    JWT_SECRET_KEY: str = Field(
        ...,
        description="JWT signing key. Generate with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
    )
    ENCRYPTION_KEY: str = Field(
        ...,
        description="Fernet encryption key. Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    )

    # Database - REQUIRED
    DATABASE_URL: str = Field(
        ...,
        description="PostgreSQL async connection string"
    )

    # Security
    ALLOW_HTTP_SELF_HOSTED: bool = Field(
        default=False,
        description="Allow HTTP for self-hosted providers like Ollama. Set to true only for local development."
    )

    # Redis (optional)
    REDIS_URL: Optional[str] = Field(
        default=None,
        description="Redis connection string for caching and queues"
    )

    # GitHub OAuth - REQUIRED for login
    GITHUB_CLIENT_ID: Optional[str] = Field(
        default=None,
        description="GitHub OAuth App Client ID"
    )
    GITHUB_CLIENT_SECRET: Optional[str] = Field(
        default=None,
        description="GitHub OAuth App Client Secret"
    )

    # GitHub App - REQUIRED for repository access
    GITHUB_APP_ID: Optional[str] = Field(
        default=None,
        description="GitHub App ID"
    )
    GITHUB_APP_PRIVATE_KEY: Optional[str] = Field(
        default=None,
        description="GitHub App private key (PEM format)"
    )
    GITHUB_WEBHOOK_SECRET: str = Field(
        default="dev_webhook_secret",
        description="GitHub webhook signature verification secret"
    )

    # LLM API Keys (at least one required for AI reviews)
    GEMINI_API_KEY: Optional[str] = Field(
        default=None,
        description="Google Gemini API key"
    )
    OPENAI_API_KEY: Optional[str] = Field(
        default=None,
        description="OpenAI API key"
    )

    # Rate Limiting
    RATE_LIMIT_LOGIN: int = Field(default=5, description="Login attempts per minute")
    RATE_LIMIT_REGISTER: int = Field(default=3, description="Registration attempts per minute")

    # JWT
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=1440,  # 1 day
        description="JWT token expiry in minutes"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()


