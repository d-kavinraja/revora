from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional, List

class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "Revora"
    APP_ENV: str = "development"
    
    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    
    # Security
    SECRET_KEY: str = Field(default="supersecret_change_me_in_production_12345")
    JWT_SECRET_KEY: str = Field(default="supersecret_jwt_change_me_12345")
    ENCRYPTION_KEY: str = Field(default="hT_B2V9_UfXQG7A_w9dYjL1K8O9P3V2QfT_B2V9_UfXQ=") # Fernet key must be 32 url-safe base64-encoded bytes
    
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://revora:revora_pass@localhost:5432/revora_db"

    
    # GitHub App
    GITHUB_CLIENT_ID: Optional[str] = None
    GITHUB_CLIENT_SECRET: Optional[str] = None
    GITHUB_APP_ID: Optional[str] = None
    GITHUB_APP_PRIVATE_KEY: Optional[str] = None
    GITHUB_WEBHOOK_SECRET: str = "webhook_secret_for_dev"
    
    # LLM API Keys
    GEMINI_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
