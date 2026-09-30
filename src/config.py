"""Validated, side-effect-free application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_DOMAINS = ("com", "in", "ca", "co.uk", "de", "fr", "it", "ae")


class ConfigurationError(ValueError):
    """Raised when an environment setting is unsafe or invalid."""


def _positive_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ConfigurationError(f"{name} must be at least {minimum}")
    return value


def _positive_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number") from exc
    if value < minimum:
        raise ConfigurationError(f"{name} must be at least {minimum}")
    return value


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be a boolean")


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: Path
    browser_headless: bool
    browser_binary: str | None
    browser_no_sandbox: bool
    browser_disable_dev_shm_usage: bool
    job_poll_seconds: float
    page_timeout_seconds: int
    element_timeout_seconds: int
    job_timeout_seconds: int
    min_navigation_interval_seconds: float
    max_queue_size: int
    max_search_pages: int
    max_search_queries: int
    max_competitors: int
    groq_model: str
    artifact_dir: Path
    strict_sqlite_version: bool
    browser_profile_dir: Path | None = None
    selenium_url: str | None = None
    browser_recovery_url: str | None = None
    challenge_wait_seconds: int = 300
    block_cooldown_seconds: int = 300


def get_settings() -> Settings:
    """Load local settings without opening a database or browser."""
    load_dotenv(PROJECT_ROOT / ".env")
    database_path = Path(os.getenv("APP_DATABASE_PATH", "data/amazon_competitor.sqlite3"))
    if not database_path.is_absolute():
        database_path = PROJECT_ROOT / database_path
    artifact_dir = Path(os.getenv("APP_ARTIFACT_DIR", "artifacts"))
    if not artifact_dir.is_absolute():
        artifact_dir = PROJECT_ROOT / artifact_dir
    return Settings(
        database_path=database_path,
        browser_headless=_bool("APP_BROWSER_HEADLESS", True),
        browser_binary=os.getenv("APP_BROWSER_BINARY") or None,
        browser_no_sandbox=_bool("APP_BROWSER_NO_SANDBOX", False),
        browser_disable_dev_shm_usage=_bool("APP_BROWSER_DISABLE_DEV_SHM_USAGE", False),
        job_poll_seconds=_positive_float("APP_JOB_POLL_SECONDS", 2.0),
        page_timeout_seconds=_positive_int("APP_PAGE_TIMEOUT_SECONDS", 30),
        element_timeout_seconds=_positive_int("APP_ELEMENT_TIMEOUT_SECONDS", 10),
        job_timeout_seconds=_positive_int("APP_JOB_TIMEOUT_SECONDS", 900),
        min_navigation_interval_seconds=_positive_float("APP_MIN_NAVIGATION_INTERVAL_SECONDS", 2.0),
        max_queue_size=_positive_int("APP_MAX_QUEUE_SIZE", 20),
        max_search_pages=_positive_int("APP_MAX_SEARCH_PAGES", 2),
        max_search_queries=_positive_int("APP_MAX_SEARCH_QUERIES", 3),
        max_competitors=_positive_int("APP_MAX_COMPETITORS", 20),
        groq_model=os.getenv("APP_GROQ_MODEL", "openai/gpt-oss-20b").strip(),
        artifact_dir=artifact_dir,
        strict_sqlite_version=_bool("APP_STRICT_SQLITE_VERSION", False),
        browser_profile_dir=database_path.parent / "browser-profiles",
        selenium_url=os.getenv("APP_SELENIUM_URL") or None,
        browser_recovery_url=os.getenv("APP_BROWSER_RECOVERY_URL") or None,
        challenge_wait_seconds=_positive_int("APP_CHALLENGE_WAIT_SECONDS", 300),
        block_cooldown_seconds=_positive_int("APP_BLOCK_COOLDOWN_SECONDS", 300),
    )
