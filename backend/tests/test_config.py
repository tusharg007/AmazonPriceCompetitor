"""Unit tests for configuration and settings management."""

from pathlib import Path

import pytest
from app.core.config import Settings


def test_settings_default_values() -> None:
    settings = Settings()
    assert settings.app_name == "Amazon Competitor Intelligence V2"
    assert settings.app_version == "2.0.0"
    assert settings.app_env in ("development", "testing", "production")
    assert settings.evidence_dir.exists()


def test_settings_evidence_dir_creation(tmp_path: Path) -> None:
    custom_evidence = tmp_path / "sub" / "evidence_store"
    assert not custom_evidence.exists()
    settings = Settings(evidence_dir=custom_evidence)
    assert settings.evidence_dir.exists()
    assert settings.evidence_dir == custom_evidence.resolve()


def test_settings_environment_override(monkeypatch) -> None:
    monkeypatch.setenv("APP_PAGE_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("APP_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("APP_PLAYWRIGHT_HEADLESS", "false")

    settings = Settings()
    assert settings.page_timeout_seconds == 45
    assert settings.log_level == "DEBUG"
    assert settings.playwright_headless is False


def test_documented_cors_environment_variable(monkeypatch) -> None:
    monkeypatch.setenv("APP_ALLOWED_ORIGINS", "https://one.example, https://two.example")
    settings = Settings()
    assert settings.allowed_origins == ["https://one.example", "https://two.example"]


@pytest.mark.parametrize("name", ["DATABASE_URL", "APP_DATABASE_URL"])
def test_postgres_environment_url_is_respected(monkeypatch, name) -> None:
    monkeypatch.delenv("APP_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    url = "postgresql+asyncpg://aci:aci@localhost/aci_test"
    monkeypatch.setenv(name, url)
    assert Settings().database_url == url


@pytest.mark.parametrize("field", ["page_timeout_seconds", "element_timeout_seconds"])
def test_timeouts_must_be_positive(field, tmp_path) -> None:
    with pytest.raises(ValueError):
        Settings(evidence_dir=tmp_path, **{field: 0})


def test_relative_browser_path_and_postgres_url(tmp_path) -> None:
    settings = Settings(
        playwright_browsers_path=".browsers",
        evidence_dir=tmp_path / "new" / "evidence",
        database_url="postgresql+asyncpg://aci:aci@localhost/aci_test",
    )
    assert Path(settings.playwright_browsers_path).is_absolute()
    assert settings.evidence_dir.is_absolute()
    assert settings.database_url.startswith("postgresql+asyncpg://")
    hermetic = Settings(playwright_browsers_path="0", evidence_dir=tmp_path)
    assert hermetic.playwright_browsers_path == "0"
