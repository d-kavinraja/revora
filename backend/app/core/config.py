"""Application configuration.

All secrets are required via environment variables.
No hardcoded defaults for security-sensitive values.
"""

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

import re

def _kllm_gcp_config_defaults() -> tuple[str, str | None]:
    try:
        from pathlib import Path
        import json
        p = Path.home() / ".config" / "kllm-gcp" / "config.json"
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            relay = str(data.get("relay_url") or "").strip()
            key = str(data.get("api_key") or "").strip() or None
            return relay, key
    except Exception:
        pass
    return "", None



# --- hosted Ollama keep_alive -----------------------------------------------
#
# Ollama parses a *string* keep_alive with Go's time.ParseDuration and a JSON
# *number* as a whole number of seconds. A negative value keeps the model
# resident. Both forms are accepted here; a unitless integer is sent back as a
# number so Ollama does not try (and fail) to parse it as a duration.
_KEEP_ALIVE_DURATION_RE = re.compile(
    r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:ns|us|\u00b5s|\u03bcs|ms|s|m|h)"
    r"(?:(?:\d+(?:\.\d*)?|\.\d+)(?:ns|us|\u00b5s|\u03bcs|ms|s|m|h))*$"
)
_KEEP_ALIVE_SECONDS_RE = re.compile(r"^[+-]?\d+$")

KEEP_ALIVE_FORMAT_HINT = (
    "must be a Go duration (e.g. 5m, 30s, 1h) or a whole number of seconds "
    "(e.g. 300, -1)"
)


def keep_alive_is_valid(value: object) -> bool:
    """Return True when ``value`` is a keep_alive Ollama can parse."""
    if value is None:
        return True
    text = str(value).strip()
    if not text:
        # Ollama falls back to its own default for an empty string.
        return True
    if _KEEP_ALIVE_SECONDS_RE.fullmatch(text):
        return True
    return bool(_KEEP_ALIVE_DURATION_RE.fullmatch(text))


def keep_alive_payload_value(value: object) -> str | int:
    """Return the keep_alive value to send: a number when it has no unit."""
    text = str(value if value is not None else "").strip()
    if _KEEP_ALIVE_SECONDS_RE.fullmatch(text):
        return int(text)
    return text


def validate_keep_alive_duration(value: str) -> str:
    """Validate ``REVORA_HOSTED_OLLAMA_KEEP_ALIVE`` against Ollama's formats."""
    if not keep_alive_is_valid(value):
        # The rejected value is deliberately not echoed: configuration values are
        # never written to logs. Only the setting name and accepted forms appear.
        raise ValueError(f"REVORA_HOSTED_OLLAMA_KEEP_ALIVE {KEEP_ALIVE_FORMAT_HINT}.")
    return value


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

    # Optional regex for additional allowed origins. In development this
    # defaults to any localhost/127.0.0.1 port so Vite/Next can pick an
    # arbitrary port without a 400 preflight. Never set this to a wildcard
    # in production.
    CORS_ORIGIN_REGEX: str | None = Field(
        default=None,
        description="Optional regex for allowed CORS origins.",
    )

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

    # Database pool (optional; only applied when set)
    DATABASE_POOL_SIZE: int | None = Field(
        default=None, description="SQLAlchemy pool size (None = driver default)"
    )
    DATABASE_MAX_OVERFLOW: int | None = Field(
        default=None, description="SQLAlchemy max overflow (None = driver default)"
    )
    DATABASE_POOL_TIMEOUT: float | None = Field(
        default=None, description="SQLAlchemy pool checkout timeout seconds (None = default)"
    )
    DATABASE_POOL_RECYCLE: int | None = Field(
        default=None,
        description="SQLAlchemy pool recycle seconds (None = default; set e.g. 300 for Neon)",
    )

    # Security
    ALLOW_HTTP_SELF_HOSTED: bool = Field(
        default=False,
        description="Allow HTTP for self-hosted providers like Ollama. Set to true only for local development.",
    )

    # kLLM managed local inference (server-owned provider).
    # Disabled by default: every routing, mapping, execution and dashboard
    # path stays gated until an operator opts in. The seeded `kllm` provider
    # row is also disabled, so enabling requires BOTH this flag and an admin
    # enabling the provider (never a half-enabled state).
    KLLM_ENABLED: bool = Field(
        default=False,
        description="Enable the managed local kLLM provider and dashboard",
    )
    KLLM_SERVER_URL: str = Field(
        default="http://127.0.0.1:8080",
        description="Server-side base URL of the kLLM relay (never sent to clients)",
    )
    # Optional server-side gateway key for non-loopback kLLM deployments.
    # Local (127.0.0.1) requests need no key. Never exposed by the API.
    KLLM_GATEWAY_API_KEY: str | None = Field(
        default=None,
        description="Optional server-side kLLM gateway key (never exposed)",
    )
    KLLM_STATE_TIMEOUT_S: float = Field(
        default=8.0, ge=1.0, description="Timeout for kLLM state/backends reads"
    )
    KLLM_TELEMETRY_TIMEOUT_S: float = Field(
        default=5.0, ge=1.0, description="Timeout for kLLM telemetry reads"
    )

    # kLLM Cloud (Revora-managed remote kLLM relay over the GCP gateway).
    # A completely separate provider from the local managed kLLM: its own
    # namespace (kllm-cloud:<model>), its own relay, its own credentials and
    # its own per-model approval catalogue. Disabled by default; enabling needs
    # BOTH this flag and an admin enabling the `kllm-cloud` provider row.
    # Only three relay endpoints are ever used: GET /v1/models (catalogue +
    # liveness), GET /health (backend-warm probe) and POST /v1/chat/completions.
    KLLM_CLOUD_ENABLED: bool = Field(
        default=False,
        description="Enable the Revora-managed kLLM Cloud provider",
    )
    KLLM_CLOUD_BASE_URL: str = Field(
        default="",
        description="Server-side origin of the kLLM Cloud relay (never sent to clients)",
    )
    KLLM_CLOUD_API_KEY: str | None = Field(
        default=None,
        description="Optional server-side gateway key for the kLLM Cloud relay (never exposed)",
    )
    KLLM_CLOUD_DEFAULT_MODEL: str = Field(
        default="qwen3.8-27b",
        description="Fallback default model for kLLM Cloud when no approved model is chosen",
    )
    KLLM_CLOUD_TIMEOUT: float = Field(
        default=300.0,
        ge=1.0,
        description="Read timeout backstop for kLLM Cloud inference and probe requests",
    )
    KLLM_CLOUD_CONNECT_TIMEOUT_S: float = Field(
        default=10.0, ge=1.0, description="Connect timeout for kLLM Cloud requests"
    )
    KLLM_CLOUD_CONCURRENCY_LIMIT: int = Field(
        default=4, ge=1, description="Global cap on concurrent kLLM Cloud inference requests"
    )
    KLLM_CLOUD_QUEUE_TIMEOUT_S: float = Field(
        default=30.0, ge=0.0, description="Max time a kLLM Cloud request waits for a permit"
    )
    # Cloud-only stream deadlines (seconds). These are service-level deadlines,
    # distinct from the per-read transport timeout KLLM_CLOUD_TIMEOUT. They are
    # deliberately Cloud-specific so local kLLM / Hosted Ollama keep their
    # existing behaviour. The prefill deadline is absolute from request start and
    # is NOT reset by relay keepalives or by status events.
    KLLM_CLOUD_FIRST_TOKEN_TIMEOUT_S: float = Field(
        default=120.0,
        ge=1.0,
        le=600.0,
        description="Absolute prefill deadline for a kLLM Cloud request (seconds)",
    )
    KLLM_CLOUD_IDLE_TIMEOUT_S: float = Field(
        default=60.0,
        ge=1.0,
        le=600.0,
        description="Content-idle deadline for a kLLM Cloud request (seconds)",
    )
    KLLM_CLOUD_TOTAL_TIMEOUT_S: float = Field(
        default=180.0,
        ge=1.0,
        le=600.0,
        description="Absolute total deadline for a kLLM Cloud request (seconds)",
    )
    KLLM_CLOUD_STATUS_INTERVAL_S: float = Field(
        default=15.0,
        ge=1.0,
        le=120.0,
        description="Minimum interval between client-visible Cloud waiting status events",
    )
    KLLM_CLOUD_DIAGNOSTICS: bool = Field(
        default=False,
        description="Enable developer-only Cloud Chat timing diagnostics (no message content)",
    )
    KLLM_CLOUD_PROBE_TIMEOUT_S: float = Field(
        default=12.0,
        ge=2.0,
        le=60.0,
        description="Timeout for bounded model-readiness verification probes",
    )
    KLLM_CLOUD_CATALOG_CACHE_TTL: float = Field(
        default=60.0, ge=1.0, description="TTL for the kLLM Cloud catalogue snapshot"
    )
    KLLM_CLOUD_ALLOW_HTTP: bool = Field(
        default=False,
        description="Allow plain-HTTP kLLM Cloud relay URLs (development/testing only)",
    )
    # Cost policy for the Revora-managed relay. The relay billing model is not
    # documented in this repository, so the default follows the existing
    # managed-provider convention (kllm / ollama_cloud: zero marginal cost).
    # An operator billed per token sets the real rates here instead of relying
    # on the generic fallback used for unknown third-party providers.
    KLLM_CLOUD_INPUT_COST_PER_1K: float = Field(
        default=0.0,
        ge=0.0,
        description="Optional kLLM Cloud input cost per 1K tokens (USD)",
    )
    KLLM_CLOUD_OUTPUT_COST_PER_1K: float = Field(
        default=0.0,
        ge=0.0,
        description="Optional kLLM Cloud output cost per 1K tokens (USD)",
    )

    # Hosted Ollama (Revora-managed remote inference for Chat only).
    # A separate namespace from kLLM so enabling/disabling hosted models never
    # touches the kLLM provider, its readiness or its review pathway. Disabled
    # by default; an operator must opt in via environment AND the admin
    # selection toggle. Only runtime-loaded models (/api/ps) are ever exposed.
    REVORA_HOSTED_OLLAMA_ENABLED: bool = Field(
        default=False,
        description="Enable the Revora-managed hosted Ollama provider for Chat",
    )
    REVORA_HOSTED_OLLAMA_BASE_URL: str = Field(
        default="",
        description="Server-side base URL of the hosted Ollama endpoint (never sent to clients)",
    )
    REVORA_HOSTED_OLLAMA_TOKEN: str | None = Field(
        default=None,
        description="Optional server-side bearer token for the hosted Ollama endpoint (never exposed)",
    )
    REVORA_HOSTED_OLLAMA_URL_TOKEN: str | None = Field(
        default=None,
        description="Optional private-port gateway token appended as _token to hosted Ollama requests (server-side only)",
    )
    REVORA_HOSTED_OLLAMA_DISCOVERY_TIMEOUT_S: float = Field(
        default=5.0, ge=1.0, description="Timeout for hosted Ollama discovery reads (/api/ps, /api/tags)"
    )
    REVORA_HOSTED_OLLAMA_CONNECT_TIMEOUT_S: float = Field(
        default=5.0, ge=1.0, description="Connect timeout for hosted Ollama inference requests"
    )
    REVORA_HOSTED_OLLAMA_READ_TIMEOUT_S: float = Field(
        default=300.0, ge=1.0, description="Read timeout backstop for hosted Ollama inference streams"
    )
    REVORA_HOSTED_OLLAMA_CACHE_TTL_S: float = Field(
        default=15.0, ge=1.0, description="TTL for the hosted Ollama discovery cache"
    )
    REVORA_HOSTED_OLLAMA_KEEP_ALIVE: str = Field(
        default="5m",
        description="keep_alive sent with hosted inference so a served model stays resident",
    )
    REVORA_HOSTED_OLLAMA_MAX_CONCURRENT_REQUESTS: int = Field(
        default=2, ge=1, description="Global cap on concurrent hosted Ollama inference requests"
    )
    REVORA_HOSTED_OLLAMA_MAX_CONCURRENT_REQUESTS_PER_MODEL: int = Field(
        default=1, ge=1, description="Per-model cap on concurrent hosted Ollama inference requests"
    )
    REVORA_HOSTED_OLLAMA_QUEUE_TIMEOUT_S: float = Field(
        default=30.0, ge=0.0, description="Max time a hosted request waits for a concurrency permit"
    )

    # Private Whisper-Tiny English speech-to-text, used only for the chat
    # composer. The backend never owns a model or an inference queue: every
    # request goes to one private service that owns the single global model
    # slot. Disabled by default at the environment level AND by the admin
    # Speech toggle; both must be on. No audio or transcript is stored.
    REVORA_SPEECH_ENABLED: bool = Field(
        default=False,
        description="Environment kill switch for private speech-to-text (admin toggle also required)",
    )
    REVORA_SPEECH_BASE_URL: str = Field(
        default="",
        description="Server-side base URL of the private Whisper service (never exposed)",
    )
    REVORA_SPEECH_TOKEN: str | None = Field(
        default=None,
        description="Server-side bearer token for the private Whisper service (never exposed)",
    )
    REVORA_SPEECH_CONNECT_TIMEOUT_S: float = Field(
        default=5.0, ge=1.0, le=30.0, description="Connect timeout for the private speech service"
    )
    REVORA_SPEECH_READ_TIMEOUT_S: float = Field(
        default=300.0, ge=10.0, le=300.0, description="Read timeout for a speech stream backstop"
    )
    REVORA_SPEECH_WRITE_TIMEOUT_S: float = Field(
        default=30.0, ge=5.0, le=120.0, description="Write timeout for an audio upload"
    )
    REVORA_SPEECH_MAX_CONCURRENT_REQUESTS: int = Field(
        default=4, ge=1, le=8, description="Per-worker cap on admitted speech requests"
    )
    REVORA_SPEECH_QUEUE_TIMEOUT_S: float = Field(
        default=30.0, ge=5.0, le=60.0, description="Default queue timeout sent to the speech service"
    )
    REVORA_SPEECH_RATE_PER_MINUTE: int = Field(
        default=6, ge=1, le=30, description="Per-user speech request rate limit"
    )
    REVORA_SPEECH_MAX_AUDIO_MB: int = Field(
        default=5, ge=1, le=5, description="Operator ceiling for a speech upload"
    )
    REVORA_SPEECH_MAX_RECORDING_SECONDS: int = Field(
        default=60, ge=5, le=60, description="Operator ceiling for a speech recording"
    )

    # Chat concurrency and lease lifecycle (in-process, per worker). A user may
    # stream a bounded number of chats at once; one chat stays single-flight and
    # other users are always isolated. Expired leases are recovered lazily on the
    # next admission, so a crashed worker cannot reserve capacity past the TTL.
    CHAT_MAX_CONCURRENT_REQUESTS_PER_USER: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Maximum concurrent chat generations per user",
    )
    CHAT_LEASE_TTL_SECONDS: float = Field(
        default=900.0,
        ge=30.0,
        description="Chat lease TTL; an abandoned lease is recovered after this",
    )

    # Hosted machine wake / recovery (InstaBox). Optional and off by default.
    # Revora never changes the remote Ollama binding; it only wakes the machine
    # and holds an activity lease so an idle pause cannot interrupt a request.
    REVORA_HOSTED_WAKE_ENABLED: bool = Field(
        default=False,
        description="Allow Revora to wake the hosted machine when it is asleep",
    )
    REVORA_HOSTED_WAKE_API_BASE_URL: str = Field(
        default="",
        description="Server-side base URL of the machine wake API (never sent to clients)",
    )
    REVORA_HOSTED_WAKE_MACHINE_ID: str = Field(
        default="",
        description="Identifier of the hosted machine to wake (server-side only)",
    )
    REVORA_HOSTED_WAKE_API_KEY: str | None = Field(
        default=None,
        description="Server-side bearer key for the wake API (never exposed)",
    )
    REVORA_HOSTED_WAKE_TIMEOUT_S: float = Field(
        default=60.0, ge=1.0, description="Timeout for a single wake API call"
    )
    REVORA_HOSTED_READY_TIMEOUT_S: float = Field(
        default=120.0, ge=1.0, description="Max time to wait for the hosted endpoint to become ready after a wake"
    )
    REVORA_HOSTED_LEASE_TTL_S: int = Field(
        default=600, ge=30, le=3600, description="TTL of the activity lease held during hosted inference"
    )

    # Session-aware hosted monitoring (backend-coordinated, shared).
    REVORA_HOSTED_MONITOR_ENABLED: bool = Field(
        default=True,
        description="Monitor hosted availability while an authenticated session is active",
    )
    REVORA_HOSTED_MONITOR_INTERVAL_S: float = Field(
        default=20.0, ge=5.0, le=600.0,
        description="Global minimum interval between hosted monitoring cycles",
    )
    REVORA_HOSTED_READY_POLL_INTERVAL_S: float = Field(
        default=0.5, ge=0.1, le=10.0,
        description="Initial backoff interval while polling readiness after a wake",
    )
    REVORA_HOSTED_WAKE_COOLDOWN_S: float = Field(
        default=300.0, ge=30.0, le=3600.0,
        description="Local cooldown after a failed wake attempt (API retry-after takes precedence)",
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
    # Master flag for usage tracking and analytics subsystem.
    # Default True; admins may disable at runtime via the Admin Portal
    # (persisted in platform_settings['usage_analytics']).
    USAGE_ANALYTICS_ENABLED: bool = Field(
        default=True,
        description="Default master flag for usage tracking and analytics subsystem",
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

    # Admin console bootstrap (optional; values never committed).
    # If ADMIN_BOOTSTRAP_USERNAME is set and no admin with that username
    # exists, startup creates it from one of the password fields. An
    # existing admin is never overwritten or rotated implicitly.
    ADMIN_BOOTSTRAP_USERNAME: str | None = Field(
        default=None, description="Optional admin username provisioned at startup"
    )
    ADMIN_BOOTSTRAP_PASSWORD: str | None = Field(
        default=None, description="Bootstrap admin password (env only, never committed)"
    )
    ADMIN_BOOTSTRAP_PASSWORD_HASH: str | None = Field(
        default=None, description="Bcrypt hash alternative to ADMIN_BOOTSTRAP_PASSWORD"
    )

    # Real-time / background sync
    PR_STATE_SYNC_INTERVAL_MINUTES: int = Field(
        default=3,
        description="DEPRECATED — alias for SYNC_RECOVERY_INTERVAL_MINUTES (kept for back-compat)",
    )
    # Persistent operation worker (Render Free: runs inside the web process).
    OPERATION_WORKER_ENABLED: bool = Field(default=True, description="Enable the persistent operation worker")
    OPERATION_WORKER_CONCURRENCY: int = Field(default=1, description="Max concurrent operation jobs")
    OPERATION_POLL_INTERVAL_SECONDS: float = Field(default=1.0, description="Operation worker poll interval")
    OPERATION_LEASE_SECONDS: int = Field(default=90, description="Operation job lease duration")
    OPERATION_HEARTBEAT_SECONDS: int = Field(default=15, description="Operation job heartbeat interval")
    OPERATION_MAX_ATTEMPTS: int = Field(default=3, description="Maximum operation job attempts")
    OPERATION_RETRY_BACKOFF_SECONDS: int = Field(default=15, description="Base retry backoff")
    OPERATION_JOB_RETENTION_DAYS: int = Field(default=7, description="Finished operation job retention")

    # Review worker (PostgreSQL-backed job queue). When REVIEW_WORKER_ENABLED is
    # False the FastAPI lifespan does not start an in-process worker (use this
    # when a dedicated worker service/container runs instead). Concurrency is
    # the maximum number of review jobs executed simultaneously by one worker
    # process; keep the default at 1 for backward compatibility.
    REVIEW_WORKER_ENABLED: bool = Field(
        default=True, description="Start the review worker inside this process"
    )
    REVIEW_WORKER_CONCURRENCY: int = Field(
        default=5,
        ge=1,
        le=5,
        description="Max simultaneous review jobs per worker process (max 5)",
    )
    REVIEW_WORKER_POLL_INTERVAL_SECONDS: float = Field(
        default=2.0, ge=0.1, description="Review worker queue poll interval"
    )
    REVIEW_WORKER_SHUTDOWN_TIMEOUT_SECONDS: int = Field(
        default=300,
        ge=10,
        description="Graceful shutdown window for active reviews on worker stop",
    )

    # Per-provider LLM concurrency. Each provider gets its own semaphore so
    # that N concurrent reviews do not overwhelm a single provider's rate
    # limit. Applies to the LLM call only, not the whole review.
    PROVIDER_CONCURRENCY_LIMIT: int = Field(
        default=3, ge=1, le=5, description="Max concurrent LLM calls per provider (max 5)"
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

    # MouthMap Model Lab (inference-only, private Hugging Face Gradio Space)
    # Configured exclusively via environment (Render dashboard in prod,
    # backend/.env locally) — no default, so the Space URL never ships in git.
    MOUTHMAP_HF_ENDPOINT_URL: str | None = Field(
        default=None,
        description="Base URL of the hosted MouthMap Gradio Space",
    )
    MOUTHMAP_HF_API_TOKEN: str | None = Field(
        default=None,
        description="Optional HF token for private spaces. Server-side only, never exposed.",
    )
    MOUTHMAP_MAX_UPLOAD_MB: int = Field(
        default=50, description="Maximum MouthMap video upload size in megabytes"
    )
    MOUTHMAP_ALLOWED_EXTENSIONS: list[str] = Field(
        default=[".mp4", ".webm", ".mpg"],
        description="Video extensions accepted by the MouthMap service",
    )
    MOUTHMAP_HF_TIMEOUT_S: int = Field(
        default=180, description="Timeout for a full MouthMap HF inference round-trip"
    )
    MOUTHMAP_UPLOAD_TIMEOUT_S: int = Field(
        default=60, description="Timeout for the MouthMap video upload step alone"
    )
    MOUTHMAP_MAX_CONCURRENT_INFERENCES: int = Field(
        default=1,
        description="Max simultaneous MouthMap inferences; extra callers get 429",
    )
    MOUTHMAP_STREAM_CHUNK_BYTES: int = Field(
        default=1024 * 1024, description="Chunk size for streaming MouthMap uploads"
    )
    MOUTHMAP_WAKE_TIMEOUT_S: int = Field(
        default=180,
        description="Max seconds to wait for a sleeping MouthMap Space to become ready",
    )
    MOUTHMAP_WAKE_POLL_INTERVAL_S: float = Field(
        default=4.0,
        description="Seconds between readiness probes while waking the MouthMap Space",
    )
    MOUTHMAP_READY_TTL_S: int = Field(
        default=600,
        description="Seconds a confirmed-ready MouthMap Space is trusted before re-probing",
    )
    GIT_CLONE_TIMEOUT_S: int = Field(
        default=120, description="Hard timeout for a single git clone operation"
    )
    GIT_CLONE_MAX_MB: int = Field(
        default=250, description="Maximum on-disk size of a cloned repository"
    )
    MOUTHMAP_DATASET_DIR: str = Field(
        default="app/mouthmap/dataset",
        description="Server-side directory holding real test videos + .align files",
    )
    MOUTHMAP_MODEL_VERSION: str = Field(
        default="mouthmap-v1", description="Deployed MouthMap model version label"
    )

    # BotaniQ Model Lab (medicinal plant classifier, same HF Space as MouthMap)
    # Reuses MOUTHMAP_HF_ENDPOINT_URL and MOUTHMAP_HF_API_TOKEN.
    BOTANIQ_MAX_UPLOAD_MB: int = Field(
        default=20, description="Maximum BotaniQ image upload size in megabytes"
    )
    BOTANIQ_ALLOWED_EXTENSIONS: list[str] = Field(
        default=[".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"],
        description="Image extensions accepted by the BotaniQ service",
    )
    BOTANIQ_HF_TIMEOUT_S: int = Field(
        default=120, description="Timeout for a full BotaniQ HF inference round-trip"
    )
    BOTANIQ_UPLOAD_TIMEOUT_S: int = Field(
        default=60, description="Timeout for the BotaniQ image upload step alone"
    )
    BOTANIQ_MAX_CONCURRENT_INFERENCES: int = Field(
        default=2,
        description="Max simultaneous BotaniQ inferences; extra callers get 429",
    )
    BOTANIQ_STREAM_CHUNK_BYTES: int = Field(
        default=512 * 1024, description="Chunk size for streaming BotaniQ uploads"
    )
    BOTANIQ_WAKE_TIMEOUT_S: int = Field(
        default=180,
        description="Max seconds to wait for the Space to become ready for BotaniQ",
    )
    BOTANIQ_WAKE_POLL_INTERVAL_S: float = Field(
        default=4.0,
        description="Seconds between readiness probes while waking for BotaniQ",
    )
    BOTANIQ_READY_TTL_S: int = Field(
        default=600,
        description="Seconds a confirmed-ready Space is trusted before re-probing (BotaniQ)",
    )
    BOTANIQ_DATASET_DIR: str = Field(
        default="app/botaniq/dataset",
        description="Server-side directory holding BotaniQ sample images",
    )
    BOTANIQ_MODEL_VERSION: str = Field(
        default="botaniq-v1", description="Deployed BotaniQ model version label"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("REVORA_HOSTED_OLLAMA_KEEP_ALIVE")
    @classmethod
    def _validate_hosted_keep_alive(cls, value: str) -> str:
        """Fail fast on a keep_alive Ollama would reject with HTTP 400."""
        return validate_keep_alive_duration(value)

    @model_validator(mode="after")
    def validate_secrets(self) -> "Settings":
        # Ensure a real webhook secret is set in production
        if self.APP_ENV not in ("development", "testing"):
            if self.GITHUB_WEBHOOK_SECRET == "dev_webhook_secret":
                raise ValueError(
                    "GITHUB_WEBHOOK_SECRET must be set in non-development environments."
                )
            import logging

            # PyJWT's HS256 expects at least a 256-bit key; a shorter key only
            # produces an InsecureKeyLengthWarning and still signs, but it
            # should not be the norm in production.
            if len(self.JWT_SECRET_KEY.encode("utf-8")) < 32:
                logging.getLogger(__name__).warning(
                    "JWT_SECRET_KEY is %d bytes long (minimum 32 recommended for "
                    "HS256). Generate with: python -c \"import secrets; "
                    "print(secrets.token_urlsafe(32))\"",
                    len(self.JWT_SECRET_KEY.encode("utf-8")),
                )
        return self

    @model_validator(mode="after")
    def validate_kllm_cloud_stream_deadlines(self) -> "Settings":
        if not self.KLLM_CLOUD_BASE_URL:
            gcp_relay, gcp_key = _kllm_gcp_config_defaults()
            if gcp_relay:
                self.KLLM_CLOUD_BASE_URL = gcp_relay
            if not self.KLLM_CLOUD_API_KEY and gcp_key:
                self.KLLM_CLOUD_API_KEY = gcp_key
        # Cloud-only stream deadlines must form a sane, enforceable ordering:
        # prefill < total, and idle is positive. Keepalives/status events can
        # never extend any of them (enforced in chat_service, not here).
        if self.KLLM_CLOUD_IDLE_TIMEOUT_S <= 0:
            raise ValueError("KLLM_CLOUD_IDLE_TIMEOUT_S must be positive.")
        if self.KLLM_CLOUD_TOTAL_TIMEOUT_S <= self.KLLM_CLOUD_FIRST_TOKEN_TIMEOUT_S:
            raise ValueError(
                "KLLM_CLOUD_TOTAL_TIMEOUT_S must be greater than "
                "KLLM_CLOUD_FIRST_TOKEN_TIMEOUT_S."
            )
        if self.KLLM_CLOUD_STATUS_INTERVAL_S > self.KLLM_CLOUD_FIRST_TOKEN_TIMEOUT_S:
            raise ValueError(
                "KLLM_CLOUD_STATUS_INTERVAL_S must not exceed "
                "KLLM_CLOUD_FIRST_TOKEN_TIMEOUT_S."
            )
        return self


settings = Settings()
