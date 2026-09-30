from pathlib import Path

import pytest

from src.config import get_settings
from src.scraping.browser import build_chrome_options


def test_container_browser_options_are_explicit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("APP_BROWSER_BINARY", "/usr/bin/chromium")
    monkeypatch.setenv("APP_BROWSER_NO_SANDBOX", "true")
    monkeypatch.setenv("APP_BROWSER_DISABLE_DEV_SHM_USAGE", "true")

    options = build_chrome_options(get_settings(), tmp_path / "profile")

    assert options.binary_location == "/usr/bin/chromium"
    assert "--no-sandbox" in options.arguments
    assert "--disable-dev-shm-usage" in options.arguments
