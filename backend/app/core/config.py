"""Application settings loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

ROOT_DIR = Path(__file__).resolve().parents[3]
BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(ROOT_DIR / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- General -------------------------------------------------------------
    environment: Literal["development", "test", "production"] = "development"
    app_name: str = "ModelOps AI"
    log_level: str = "INFO"
    frontend_url: str = "http://localhost:5173"
    backend_url: str = "http://localhost:8000"
    cors_origins: str = ""
    static_dir: str = ""  # Built frontend (served by the backend when set or when frontend/dist exists)

    # --- Database ------------------------------------------------------------
    database_url: str = "postgresql+psycopg://modelops:modelops@127.0.0.1:5434/modelops"
    # Optional: use this database name on the DATABASE_URL server instead of the one in the URL.
    # Lets ModelOps live in its own database on a shared PostgreSQL server
    # (`python -m app.cli ensure-database` creates it).
    database_name: str = Field(default="", pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,62}$|^$")
    db_pool_size: int = 5
    db_max_overflow: int = 5

    # --- Security ------------------------------------------------------------
    jwt_secret_key: str = Field(default="", min_length=0)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 14
    master_encryption_key: str = ""
    max_request_bytes: int = 2_000_000
    # Number of reverse proxies in front of the app that append to X-Forwarded-For (Render: 1).
    # 0 = use the socket peer address. Used for IP-based rate limiting only.
    trusted_proxy_hops: int = Field(default=0, ge=0, le=5)
    login_max_failures: int = 5
    login_lockout_minutes: int = 15

    # --- Rate limits (requests per minute) ------------------------------------
    rate_limit_auth_per_minute: int = 10
    rate_limit_api_per_minute: int = 300
    rate_limit_gateway_per_minute: int = 120

    # --- Providers -------------------------------------------------------------
    openai_base_url: str = "https://api.openai.com"
    anthropic_base_url: str = "https://api.anthropic.com"
    gemini_base_url: str = "https://generativelanguage.googleapis.com"
    anthropic_version: str = "2023-06-01"
    provider_timeout_seconds: float = 120.0
    provider_connect_timeout_seconds: float = 10.0

    # --- AI Analyst --------------------------------------------------------------
    ai_analyst_provider: Literal["openai", "anthropic", ""] = ""
    ai_analyst_model: str = ""
    ai_analyst_api_key: str = ""

    @field_validator("database_url")
    @classmethod
    def _normalise_db_url(cls, value: str) -> str:
        # Render and Heroku-style URLs use postgres:// or postgresql:// — SQLAlchemy needs the driver.
        if value.startswith("postgres://"):
            value = "postgresql://" + value[len("postgres://") :]
        if value.startswith("postgresql://"):
            value = "postgresql+psycopg://" + value[len("postgresql://") :]
        return value

    @property
    def effective_database_url(self) -> str:
        if not self.database_name:
            return self.database_url
        return make_url(self.database_url).set(database=self.database_name).render_as_string(hide_password=False)

    @model_validator(mode="after")
    def _check_secrets(self) -> Settings:
        # Secrets are required in every environment: there is no insecure built-in fallback.
        if len(self.jwt_secret_key) < 32:
            raise ValueError("JWT_SECRET_KEY must be set (at least 32 characters). See .env.example.")
        keys = [k.strip() for k in self.master_encryption_key.split(",") if k.strip()]
        if not keys or any(len(k) < 32 for k in keys):
            raise ValueError("MASTER_ENCRYPTION_KEY must be set (at least 32 characters). See .env.example.")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        origins = [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]
        if not origins and not self.is_production:
            origins = [self.frontend_url.rstrip("/")]
        return origins

    @property
    def analyst_configured(self) -> bool:
        return bool(self.ai_analyst_provider and self.ai_analyst_model and self.ai_analyst_api_key)

    def resolved_static_dir(self) -> Path | None:
        candidate = Path(self.static_dir) if self.static_dir else ROOT_DIR / "frontend" / "dist"
        return candidate if (candidate / "index.html").is_file() else None


@lru_cache
def get_settings() -> Settings:
    return Settings()
