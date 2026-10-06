"""Application configuration and environment management using Pydantic Settings."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for Amazon Competitor Intelligence V2."""

    app_name: str = "Amazon Competitor Intelligence V2"
    app_version: str = "2.0.0"
    app_env: Literal["development", "testing", "production"] = "development"
    api_prefix: str = "/api"
    log_level: str = "INFO"

    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///data/amazon_competitor.db",
        validation_alias=AliasChoices("APP_DATABASE_URL", "DATABASE_URL"),
        description="Async SQLAlchemy URL: postgresql+asyncpg://... or sqlite+aiosqlite://... .",
    )
    database_echo: bool = False
    database_pool_size: int = 5
    database_max_overflow: int = 10

    # Evidence storage
    evidence_dir: Path = Field(
        default=Path("evidence"),
        description="Directory for storing raw HTML snapshots, screenshots, and metadata.",
    )

    # Playwright browser collection
    playwright_headless: bool = True
    playwright_browsers_path: str | None = None
    page_timeout_seconds: int = Field(default=30, gt=0)
    element_timeout_seconds: int = Field(default=10, gt=0)
    min_navigation_interval_seconds: float = Field(default=2.0, ge=0)
    max_search_pages: int = Field(default=2, ge=1, le=10)
    max_competitors: int = Field(default=20, ge=1, le=100)
    challenge_wait_seconds: int = 300
    block_cooldown_seconds: int = Field(default=300, ge=0)

    # Single standalone collection worker; leases never span browser-held DB transactions.
    worker_poll_interval: float = Field(default=1.0, gt=0)
    worker_lease_seconds: int = Field(default=90, ge=3)
    worker_heartbeat_seconds: float = Field(default=15.0, gt=0)

    # CORS — comma-separated list of allowed origins; default is localhost dev origins only.
    # Never use "*" together with allow_credentials.
    # Example: APP_ALLOWED_ORIGINS="https://app.example.com,https://www.example.com"
    allowed_origins_raw: str = Field(
        default="http://localhost:5173,http://localhost:3000",
        validation_alias=AliasChoices("APP_ALLOWED_ORIGINS", "APP_ALLOWED_ORIGINS_RAW"),
        description="Comma-separated list of allowed CORS origins.",
    )

    # Groq API (reserved for Phase 6, optional in Phase 1)
    groq_api_key: str | None = Field(
        default=None, repr=False, validation_alias=AliasChoices("APP_GROQ_API_KEY", "GROQ_API_KEY")
    )
    # H-6: Use a valid Groq model identifier (https://console.groq.com/docs/models)
    groq_model: str = "openai/gpt-oss-20b"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="APP_",
        extra="ignore",
        populate_by_name=True,
    )

    @model_validator(mode="after")
    def worker_intervals(self) -> Self:
        if self.worker_heartbeat_seconds >= self.worker_lease_seconds:
            raise ValueError("Worker heartbeat interval must be shorter than its lease")
        return self

    @property
    def allowed_origins(self) -> list[str]:
        """Parse comma-separated allowed_origins_raw into a list."""
        return [o.strip() for o in self.allowed_origins_raw.split(",") if o.strip()]

    @field_validator("evidence_dir", mode="after")
    @classmethod
    def resolve_evidence_dir(cls, value: Path) -> Path:
        resolved = value.resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved

    @field_validator("playwright_browsers_path", mode="after")
    @classmethod
    def resolve_browsers_path(cls, value: str | None) -> str | None:
        if value:
            if value == "0":  # Playwright's documented hermetic-install sentinel.
                return value
            return str(Path(value).expanduser().resolve())
        # Auto-detect project local .browsers if present
        local_browsers = Path(__file__).resolve().parents[3] / ".browsers"
        if local_browsers.is_dir():
            return str(local_browsers)
        # Also check current working directory
        cwd_browsers = Path.cwd() / ".browsers"
        if cwd_browsers.is_dir():
            return str(cwd_browsers)
        return os.environ.get("PLAYWRIGHT_BROWSERS_PATH")


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
