"""WebDriver lifecycle; fresh profile per job and guaranteed cleanup."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.remote.webdriver import WebDriver

from src.config import Settings


def build_chrome_options(settings: Settings, profile: Path) -> Options:
    """Build explicit browser options for local or container execution."""
    options = Options()
    if settings.browser_headless:
        options.add_argument("--headless=new")
    if settings.browser_no_sandbox:
        options.add_argument("--no-sandbox")
    if settings.browser_disable_dev_shm_usage:
        options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1440,1200")
    options.add_argument(f"--user-data-dir={profile}")
    options.add_argument("--lang=en-US")
    options.page_load_strategy = "eager"
    if settings.browser_binary:
        options.binary_location = settings.browser_binary
    return options


@contextmanager
def chrome_session(settings: Settings, domain: str) -> Iterator[WebDriver]:
    del domain
    profile = Path(tempfile.mkdtemp(prefix="amazon-competitor-"))
    driver: WebDriver | None = None
    try:
        options = build_chrome_options(settings, profile)
        driver = webdriver.Chrome(options=options)
        driver.implicitly_wait(0)
        driver.set_page_load_timeout(settings.page_timeout_seconds)
        driver.set_script_timeout(settings.page_timeout_seconds)
        yield driver
    finally:
        if driver is not None:
            driver.quit()
        shutil.rmtree(profile, ignore_errors=True)
