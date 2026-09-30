"""WebDriver lifecycle with persistent marketplace profiles and guaranteed cleanup."""

from __future__ import annotations

import shutil
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.remote.webdriver import WebDriver

from src.config import Settings
from src.models import normalize_domain


@contextmanager
def profile_lock(profile: Path) -> Iterator[None]:
    """OS locks release on worker crashes, unlike an exclusive lock-file sentinel."""
    with (profile / "worker.lock").open("a+b") as lock_file:
        if lock_file.tell() == 0:
            lock_file.write(b"0")
            lock_file.flush()
        lock_file.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("This marketplace browser profile is already in use") from exc
        try:
            yield
        finally:
            if sys.platform == "win32":
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


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
    if settings.browser_binary and not settings.selenium_url:
        options.binary_location = settings.browser_binary
    return options


@contextmanager
def chrome_session(settings: Settings, domain: str) -> Iterator[WebDriver]:
    domain = normalize_domain(domain)
    persistent = settings.browser_profile_dir is not None
    profile = (
        settings.browser_profile_dir / domain
        if settings.browser_profile_dir is not None
        else Path(tempfile.mkdtemp(prefix="amazon-competitor-"))
    )
    profile.mkdir(parents=True, exist_ok=True)
    # The single worker owns a profile for the lifetime of its browser session.
    # A second worker fails safely rather than opening the same profile concurrently.
    driver: WebDriver | None = None
    try:
        with profile_lock(profile):
            browser_profile = (
                Path(f"/home/seluser/amazon-profiles/{domain}")
                if settings.selenium_url
                else profile
            )
            options = build_chrome_options(settings, browser_profile)
            driver = (
                webdriver.Remote(command_executor=settings.selenium_url, options=options)
                if settings.selenium_url
                else webdriver.Chrome(options=options)
            )
            try:
                driver.implicitly_wait(0)
                driver.set_page_load_timeout(settings.page_timeout_seconds)
                driver.set_script_timeout(settings.page_timeout_seconds)
                yield driver
            finally:
                driver.quit()
    finally:
        if not persistent:
            shutil.rmtree(profile, ignore_errors=True)
