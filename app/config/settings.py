from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


# ==========================================================
# Base directory
# ==========================================================

BASE_DIR = (
    Path(__file__)
    .resolve()
    .parent
    .parent
    .parent
)


# ==========================================================
# Settings
# ==========================================================

class Settings(BaseSettings):
    """
    Application configuration.

    Priority:

        environment variables
        >
        .env
        >
        default values
    """

    model_config = SettingsConfigDict(
        env_file=str(
            BASE_DIR / "config" / ".env"
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ======================================================
    # Application
    # ======================================================

    app_name: str = (
        "AI Semantic Cache Gateway"
    )

    app_version: str = "2.0.0"

    host: str = "0.0.0.0"

    port: int = 8000

    app_env: str = "development"

    # Comma-separated exact browser origins. Wildcards are rejected in production.
    cors_allowed_origins: str = "http://127.0.0.1:8000,http://localhost:8000"

    cookie_secure: bool = False

    cookie_samesite: str = "lax"

    csrf_enabled: bool = True

    csrf_cookie_name: str = "ascg_csrf_token"

    csrf_header_name: str = "X-CSRF-Token"

    rate_limit_enabled: bool = True

    rate_limit_fail_closed: bool = True

    auth_rate_limit_per_minute: int = 10

    provider_test_rate_limit_per_minute: int = 5

    workspace_request_rate_limit_per_minute: int = 60

    workspace_max_concurrent_requests: int = 8

    global_max_concurrent_requests: int = 32

    # Leave empty for the existing local SQLite backend. When set, the
    # application requires the PostgreSQL schema to be migrated explicitly.
    database_url: str | None = None

    database_connect_timeout: int = 5

    database_pool_min_size: int = 1

    database_pool_max_size: int = 10

    # BYOK is intentionally opt-in. Production mode never falls back to
    # provider keys stored in the process environment.
    byok_enabled: bool = False

    allow_global_provider_fallback: bool = True

    provider_credential_encryption_key: str | None = None

    # ======================================================
    # Default LLM
    # ======================================================

    default_provider: str = "deepseek"

    default_model: str = "deepseek-chat"

    # ======================================================
    # LLM Client
    # ======================================================

    llm_timeout: float = 30.0

    llm_max_retries: int = 0

    # Runtime values that can be changed from the authenticated dashboard.
    # Secrets remain environment-only and are never written to this file.
    log_level: str = "INFO"

    log_to_file: bool = False

    log_file: str = "logs/gateway.log"

    auth_token_expiration_hours: int = 24

    notifications_enabled: bool = False

    # ======================================================
    # DeepSeek
    # ======================================================

    deepseek_api_key: str | None = None

    deepseek_base_url: str = (
        "https://api.deepseek.com"
    )

    deepseek_model: str = (
        "deepseek-chat"
    )

    # Optional comma-separated additional models using the same endpoint/key.
    deepseek_models: str = ""

    # ======================================================
    # OpenAI
    # ======================================================

    openai_api_key: str | None = None

    openai_base_url: str = (
        "https://api.openai.com/v1"
    )

    openai_model: str = (
        "gpt-5-nano"
    )

    openai_models: str = ""

    # ======================================================
    # Qwen Classifier
    #
    # Qwen3.8-Flash is used as the lightweight
    # modality classifier.
    #
    # Its job is to determine whether a request
    # is mainly:
    #
    #   text
    #   image
    #
    # It is NOT the final answer model.
    # ======================================================

    qwen_classifier_api_key: str | None = None

    qwen_classifier_base_url: str = (
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )

    qwen_classifier_model: str = (
        "qwen3.8-flash"
    )

    # ======================================================
    # Qwen Image
    # ======================================================

    qwen_image_api_key: str | None = None

    qwen_image_base_url: str = (
        "https://dashscope.aliyuncs.com/api/v1"
    )

    qwen_image_model: str = (
        "qwen-image-3.0"
    )

    qwen_image_models: str = ""

    # Generated images are private resources. Local storage is intended for
    # development; production should use an S3-compatible bucket.
    image_storage_backend: str = "local"
    image_storage_path: str = str(BASE_DIR / "data" / "media")
    image_max_bytes: int = 10 * 1024 * 1024
    image_max_per_workspace: int = 1000
    image_max_workspace_bytes: int = 1024 * 1024 * 1024
    image_fetch_timeout: float = 30.0
    image_upload_retries: int = 2
    image_presign_ttl: int = 300
    image_source_allowlist: str = "aliyuncs.com,aliyun.com"
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None
    s3_region: str = "auto"
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_session_token: str | None = None

    # ======================================================
    # Redis
    # ======================================================

    redis_url: str = (
        "redis://localhost:6379"
    )

    @property
    def redis_host(self) -> str:
        try:
            value = (
                self.redis_url
                .replace(
                    "redis://",
                    "",
                )
                .replace(
                    "rediss://",
                    "",
                )
            )

            return value.split(":")[0]

        except Exception:
            return "localhost"

    @property
    def redis_port(self) -> int:
        try:
            value = (
                self.redis_url
                .replace(
                    "redis://",
                    "",
                )
                .replace(
                    "rediss://",
                    "",
                )
            )

            port = value.split(":")[-1]

            return int(port)

        except Exception:
            return 6379

    # ======================================================
    # Cache
    # ======================================================

    cache_threshold: float = 0.75

    cache_ttl: int = 86400

    semantic_cache_enabled: bool = True

    exact_cache_enabled: bool = True

    cache_max_answer_length: int = 20000

    cache_index_name: str = (
        "cache_idx"
    )

    cache_key_prefix: str = (
        "cache:entry:"
    )

    vector_dimension: int = 512

    distance_metric: str = "COSINE"

    vector_algorithm: str = "HNSW"

    # ======================================================
    # Embedding
    # ======================================================

    embedding_model: str = (
        "BAAI/bge-small-zh-v1.5"
    )

    embedding_model_path: str | None = None

    embedding_model_local_only: bool = False

    embedding_cache_dir: str | None = None

    # ======================================================
    # Cost
    # ======================================================

    enable_cost_tracking: bool = True

    # ======================================================
    # Routing
    # ======================================================

    routing_enable_image: bool = True

    routing_enable_text: bool = True

    # ======================================================
    # User-defined OpenAI-compatible providers
    # ======================================================

    custom_providers_file: str = str(
        BASE_DIR / "config" / "providers.json"
    )

    # ======================================================
    # Authentication
    # ======================================================

    auth_secret_key: str | None = None

    # Immutable server-side administrator binding. This is intentionally an
    # integer user id rather than an email so a user cannot change their
    # address and inherit platform privileges.
    admin_user_id: int | None = None

    admin_email: str | None = None

    auth_frontend_url: str = (
        "http://127.0.0.1:8000"
    )

    # OAuth login providers. Secrets are environment-only and never written
    # to runtime settings or returned by management APIs.
    github_oauth_client_id: str | None = None

    github_oauth_client_secret: str | None = None

    google_oauth_client_id: str | None = None

    google_oauth_client_secret: str | None = None

    # ======================================================
    # SMTP / Email
    # ======================================================

    smtp_host: str | None = None

    smtp_port: int = 587

    smtp_username: str | None = None

    smtp_password: str | None = None

    smtp_from_email: str | None = None

    smtp_use_tls: bool = True

    smtp_timeout_seconds: int = 10

    # Railway may block outbound SMTP. Production can use the HTTPS Resend
    # API while local development keeps the existing SMTP path.
    email_provider: str = "smtp"

    resend_api_key: str | None = None

    resend_from_email: str | None = None

    # ======================================================
    # Provider configuration helpers
    # ======================================================

    def is_deepseek_configured(
        self,
    ) -> bool:
        return bool(
            self.deepseek_api_key
            and str(
                self.deepseek_api_key
            ).strip()
        )

    def is_openai_configured(
        self,
    ) -> bool:
        return bool(
            self.openai_api_key
            and str(
                self.openai_api_key
            ).strip()
        )

    def is_qwen_classifier_configured(
        self,
    ) -> bool:
        return bool(
            self.qwen_classifier_api_key
            and str(
                self.qwen_classifier_api_key
            ).strip()
        )

    def is_qwen_image_configured(
        self,
    ) -> bool:
        return bool(
            self.qwen_image_api_key
            and str(
                self.qwen_image_api_key
            ).strip()
            and self.qwen_image_base_url
            and str(
                self.qwen_image_base_url
            ).strip()
        )

    def model_names(self, provider: str) -> list[str]:
        """Return the primary model plus optional runtime-configured models."""
        name = str(provider or "").strip().lower()
        primary = str(getattr(self, f"{name}_model", "") or "").strip()
        extras = str(getattr(self, f"{name}_models", "") or "")
        values = [primary, *(item.strip() for item in extras.split(","))]
        return list(dict.fromkeys(item for item in values if item))

    # ======================================================
    # Authentication helpers
    # ======================================================

    def is_auth_configured(
        self,
    ) -> bool:
        return bool(
            self.auth_secret_key
            and str(
                self.auth_secret_key
            ).strip()
        )

    @property
    def production_mode(self) -> bool:
        return str(self.app_env or "").strip().lower() in {
            "production",
            "prod",
        }

    @property
    def byok_required(self) -> bool:
        return bool(self.byok_enabled or self.production_mode)

    @property
    def global_provider_fallback_allowed(self) -> bool:
        return bool(self.allow_global_provider_fallback and not self.production_mode)

    @property
    def cors_origins(self) -> list[str]:
        values = [item.strip().rstrip("/") for item in str(self.cors_allowed_origins or "").split(",")]
        return list(dict.fromkeys(item for item in values if item))

    @property
    def effective_cookie_secure(self) -> bool:
        return bool(self.cookie_secure or self.production_mode)

    def validate_production_configuration(self) -> list[str]:
        """Return deployment-blocking configuration errors without exposing secret values."""
        if not self.production_mode:
            return []
        errors: list[str] = []
        database_url = str(self.database_url or "").strip().lower()
        if (
            not database_url
            or database_url.startswith("sqlite:")
            or database_url.endswith(".db")
        ):
            errors.append("DATABASE_URL must point to PostgreSQL; SQLite is not allowed in production")
        if not self.byok_enabled:
            errors.append("BYOK_ENABLED must be true in production")
        if self.allow_global_provider_fallback:
            errors.append("ALLOW_GLOBAL_PROVIDER_FALLBACK must be false in production")
        if not self.is_auth_configured() or len(str(self.auth_secret_key or "")) < 32:
            errors.append("AUTH_SECRET_KEY must be configured with at least 32 characters")
        if not self.provider_credential_encryption_key:
            errors.append("PROVIDER_CREDENTIAL_ENCRYPTION_KEY must be configured")
        if not self.effective_cookie_secure:
            errors.append("COOKIE_SECURE must be true in production")
        same_site = str(self.cookie_samesite or "").lower()
        if same_site not in {"lax", "strict", "none"}:
            errors.append("COOKIE_SAMESITE must be lax, strict, or none")
        if same_site == "none" and not self.effective_cookie_secure:
            errors.append("COOKIE_SAMESITE=none requires COOKIE_SECURE=true")
        if not str(self.auth_frontend_url or "").lower().startswith("https://"):
            errors.append("AUTH_FRONTEND_URL must use HTTPS in production")
        origins = self.cors_origins
        if not origins or "*" in origins:
            errors.append("CORS_ALLOWED_ORIGINS must contain explicit HTTPS origins")
        elif any(not origin.lower().startswith("https://") for origin in origins):
            errors.append("CORS_ALLOWED_ORIGINS must not contain HTTP origins in production")
        if str(self.image_storage_backend or "").lower() != "s3":
            errors.append("IMAGE_STORAGE_BACKEND must be s3 in production")
        for name, value in {
            "S3_BUCKET": self.s3_bucket,
            "S3_ACCESS_KEY_ID": self.s3_access_key_id,
            "S3_SECRET_ACCESS_KEY": self.s3_secret_access_key,
        }.items():
            if not str(value or "").strip():
                errors.append(f"{name} must be configured for private image storage")
        redis_url = str(self.redis_url or "").lower()
        if not redis_url or "localhost" in redis_url or "127.0.0.1" in redis_url:
            errors.append("REDIS_URL must point to a production Redis service")
        if not self.embedding_model_local_only:
            errors.append("EMBEDDING_MODEL_LOCAL_ONLY must be true to prevent first-request downloads")
        model_path = self.embedding_model_path or self.embedding_cache_dir
        if not model_path or not Path(model_path).exists():
            errors.append("EMBEDDING_MODEL_PATH or EMBEDDING_CACHE_DIR must point to a bundled model cache")
        if not self.csrf_enabled:
            errors.append("CSRF_ENABLED must be true when browser cookies are enabled")
        oauth_values = {
            "GITHUB_OAUTH_CLIENT_ID": self.github_oauth_client_id,
            "GITHUB_OAUTH_CLIENT_SECRET": self.github_oauth_client_secret,
            "GOOGLE_OAUTH_CLIENT_ID": self.google_oauth_client_id,
            "GOOGLE_OAUTH_CLIENT_SECRET": self.google_oauth_client_secret,
        }
        for name, value in oauth_values.items():
            if not str(value or "").strip():
                errors.append(f"{name} must be configured for production OAuth login")
        return errors

    def require_production_configuration(self) -> None:
        errors = self.validate_production_configuration()
        if errors:
            raise RuntimeError("Production configuration is invalid: " + "; ".join(errors))

    def is_admin_configured(
        self,
    ) -> bool:
        return self.admin_user_id is not None and int(self.admin_user_id) > 0

    # ======================================================
    # SMTP helper
    # ======================================================

    @property
    def smtp_configured(self) -> bool:
        return bool(
            self.smtp_host
            and self.smtp_username
            and self.smtp_password
            and self.smtp_from_email
        )


# ==========================================================
# Cached settings instance
# ==========================================================

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


RUNTIME_SETTINGS_FILE = BASE_DIR / "config" / "runtime_settings.json"

RUNTIME_SETTING_FIELDS = {
    "app_name",
    "default_provider",
    "default_model",
    "deepseek_models",
    "openai_models",
    "qwen_image_models",
    "llm_timeout",
    "llm_max_retries",
    "cache_threshold",
    "cache_ttl",
    "semantic_cache_enabled",
    "exact_cache_enabled",
    "cache_max_answer_length",
    "log_level",
    "log_to_file",
    "log_file",
    "auth_token_expiration_hours",
    "notifications_enabled",
}


def load_runtime_settings() -> dict[str, Any]:
    """Load dashboard-owned settings without loading provider secrets."""
    if not RUNTIME_SETTINGS_FILE.exists():
        return {}

    try:
        data = json.loads(RUNTIME_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

    if not isinstance(data, dict):
        return {}

    return {
        key: value
        for key, value in data.items()
        if key in RUNTIME_SETTING_FIELDS
    }


def load_workspace_settings(workspace_id: int | str) -> dict[str, Any]:
    if not settings.database_url:
        return load_runtime_settings()
    from app.db.postgres import get_postgres_connection

    with get_postgres_connection() as conn:
        row = conn.execute(
            "SELECT settings_json FROM workspace_settings WHERE workspace_id = ?",
            (int(workspace_id),),
        ).fetchone()
    value = row["settings_json"] if row else {}
    return dict(value) if isinstance(value, dict) else {}


def save_runtime_settings(values: dict[str, Any], workspace_id: int | str | None = None) -> dict[str, Any]:
    """Persist only non-secret dashboard settings and apply them immediately."""
    current = load_workspace_settings(workspace_id) if settings.database_url and workspace_id is not None else load_runtime_settings()
    current.update(
        {
            key: value
            for key, value in values.items()
            if key in RUNTIME_SETTING_FIELDS
        }
    )
    if settings.database_url and workspace_id is not None:
        from app.db.postgres import get_postgres_connection
        from psycopg.types.json import Jsonb

        with get_postgres_connection() as conn:
            conn.execute(
                """
                INSERT INTO workspace_settings(workspace_id, settings_json, version, updated_at)
                VALUES(?, ?, 1, ?)
                ON CONFLICT(workspace_id) DO UPDATE
                SET settings_json = excluded.settings_json,
                    version = workspace_settings.version + 1,
                    updated_at = excluded.updated_at
                """,
                (int(workspace_id), Jsonb(current), datetime.now(timezone.utc).isoformat()),
            )
    else:
        RUNTIME_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = RUNTIME_SETTINGS_FILE.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(current, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(RUNTIME_SETTINGS_FILE)
    if not settings.database_url:
        for key, value in current.items():
            setattr(settings, key, value)
    return current


for _key, _value in load_runtime_settings().items():
    setattr(settings, _key, _value)


# ==========================================================
# Public exports
# ==========================================================

__all__ = [
    "BASE_DIR",
    "Settings",
    "settings",
    "get_settings",
    "RUNTIME_SETTINGS_FILE",
    "load_runtime_settings",
    "load_workspace_settings",
    "save_runtime_settings",
]
