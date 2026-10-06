"""Playwright browser collector abstraction with stealth, lifecycle management, and evidence capture."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import tempfile
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self
from urllib.parse import urlparse

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright
from playwright.async_api import Error as PlaywrightError

from app.collector import selectors
from app.collector.errors import PageNotFoundError, ScrapingBlockedError, ScrapingError
from app.core.config import Settings, get_settings
from app.models.enums import ScrapeErrorCode
from app.models.schemas import SUPPORTED_DOMAINS

logger = logging.getLogger(__name__)


async def finish_cleanup(cleanup: Awaitable[None]) -> None:
    """Finish resource teardown even if its caller is cancelled, then propagate cancellation."""
    task = asyncio.ensure_future(cleanup)
    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            cancellation = exc
    task.result()
    if cancellation is not None:
        raise cancellation


@dataclass(frozen=True)
class EvidenceArtifactData:
    """Captured raw evidence artifact payload."""

    content_hash: str
    storage_path: str
    content_size_bytes: int
    source_url: str
    collector: str
    captured_at: datetime
    evidence_type: str = "html"


class BrowserCollector(ABC):
    """Abstract browser collector.

    Use as an async context manager to manage the Playwright lifecycle:

        async with AmazonCollector(settings) as collector:
            product, evidence = await collector.collect_product(asin, domain)

    A single Playwright instance is created on entry, with contexts created lazily
    per marketplace. All are torn down on exit. This avoids the overhead and profile-locking
    problems caused by launching a new Chromium process for every page request.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._last_navigation_time: float = 0.0
        self._playwright: Playwright | None = None
        self._playwright_manager: AbstractAsyncContextManager[Playwright] | None = None
        self._browser: Browser | None = None
        # One persistent context per domain, reused across all page requests
        self._contexts: dict[str, BrowserContext] = {}
        self._context_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Async context manager for lifecycle management
    # ------------------------------------------------------------------

    async def __aenter__(self) -> Self:
        if self._playwright_manager is not None:
            raise RuntimeError("BrowserCollector is already open.")
        if self.settings.playwright_browsers_path:
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = self.settings.playwright_browsers_path
        try:
            # Keep the manager before startup awaits: start can fail/cancel before returning a handle.
            self._playwright_manager = async_playwright()
            self._playwright = await self._playwright_manager.__aenter__()
            self._browser = await self._playwright.chromium.launch(
                headless=self.settings.playwright_headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                ],
            )
        except BaseException:
            await finish_cleanup(self._close_resources())
            raise
        return self

    async def __aexit__(self, *_: object) -> None:
        await finish_cleanup(self._close_resources())

    async def _close_resources(self) -> None:
        for domain, ctx in self._contexts.items():
            try:
                profile_dir = self.settings.evidence_dir.parent / "browser-profiles" / domain
                await ctx.storage_state(path=profile_dir / "storage_state.json")
            except Exception:
                logger.exception("Error saving browser state")
            try:
                await ctx.close()
            except Exception:
                logger.exception("Error closing browser context")
        self._contexts.clear()

        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                logger.exception("Error closing browser")
            self._browser = None

        if self._playwright_manager:
            try:
                await self._playwright_manager.__aexit__(None, None, None)
            except Exception:
                logger.exception("Error stopping playwright")
            self._playwright_manager = None
        self._playwright = None

    # ------------------------------------------------------------------
    # Per-domain context (one per domain, lazily created, reused)
    # ------------------------------------------------------------------

    async def _get_context(self, domain: str) -> BrowserContext:
        """Return the persistent BrowserContext for a given domain, creating it if needed."""
        if domain not in SUPPORTED_DOMAINS:
            raise ValueError("Unsupported Amazon marketplace domain.")
        async with self._context_lock:
            if self._browser is None:
                raise RuntimeError(
                    "BrowserCollector must be used as an async context manager "
                    "('async with collector:') before calling collection methods."
                )

            if domain not in self._contexts:
                profile_dir = self.settings.evidence_dir.parent / "browser-profiles" / domain
                profile_dir.mkdir(parents=True, exist_ok=True)
                context = await self._browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    locale="en-US",
                    storage_state=self._load_storage_state(profile_dir, domain),
                )
                # Register before initialization so a script failure cannot leak this context.
                self._contexts[domain] = context
                try:
                    await self._apply_stealth(context)
                except BaseException:
                    self._contexts.pop(domain)
                    await finish_cleanup(self._close_context(context))
                    raise

        return self._contexts[domain]

    async def _close_context(self, context: BrowserContext) -> None:
        try:
            await context.close()
        except Exception:
            logger.exception("Error closing browser context")

    def _load_storage_state(self, profile_dir: Path, domain: str) -> Path | None:
        """Use persisted state only when all cookies and origins belong to this marketplace."""
        state_file = profile_dir / "storage_state.json"
        if state_file.exists():
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
                host = f"amazon.{domain}"

                def allowed_host(value: str) -> bool:
                    value = value.lstrip(".").lower()
                    return value == host or value.endswith(f".{host}")

                if not isinstance(data, dict):
                    return None
                cookies, origins = data.get("cookies"), data.get("origins")
                if not isinstance(cookies, list) or not isinstance(origins, list):
                    return None
                for cookie in cookies:
                    if not isinstance(cookie, dict) or not isinstance(cookie.get("domain"), str):
                        return None
                    if not allowed_host(cookie["domain"]):
                        return None
                for origin in origins:
                    if not isinstance(origin, dict) or not isinstance(origin.get("origin"), str):
                        return None
                    parsed = urlparse(origin["origin"])
                    if parsed.scheme != "https" or not allowed_host(parsed.hostname or ""):
                        return None
                return state_file
            except (OSError, ValueError) as exc:
                logger.warning("Could not load browser storage state from %s: %s", state_file, exc)
        return None

    async def _apply_stealth(self, context: BrowserContext) -> None:
        """Inject stealth init scripts into every page opened by this context."""
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            window.chrome = {
                runtime: {}
            };
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
        """)

    # ------------------------------------------------------------------
    # Page context manager — borrows a page from the domain context
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def session(self, domain: str) -> AsyncIterator[Page]:
        """Async context manager yielding a configured, paced, stealth Playwright Page.

        The underlying BrowserContext is reused across calls; only the Page is
        created and closed here. Use ``async with collector:`` to manage the
        full browser lifecycle.
        """
        context = await self._get_context(domain)
        page: Page = await context.new_page()
        try:
            page.set_default_timeout(self.settings.element_timeout_seconds * 1000)
            page.set_default_navigation_timeout(self.settings.page_timeout_seconds * 1000)
            yield page
        finally:
            await finish_cleanup(self._close_page(page))

    async def _close_page(self, page: Page) -> None:
        try:
            await page.close()
        except Exception:
            logger.exception("Error closing browser page")

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    async def _enforce_pacing(self) -> None:
        """Rate limit navigations to avoid rapid-fire requests."""
        loop = asyncio.get_running_loop()
        now = loop.time()
        elapsed = now - self._last_navigation_time
        interval = self.settings.min_navigation_interval_seconds
        if elapsed < interval:
            await asyncio.sleep(interval - elapsed)
        self._last_navigation_time = asyncio.get_running_loop().time()

    # ------------------------------------------------------------------
    # Page state checks
    # ------------------------------------------------------------------

    async def check_page_state(self, page: Page) -> None:
        """Scan current page for challenge, robot check, or 404 error markers."""
        for selector in selectors.BLOCK_MARKERS:
            locator = page.locator(selector)
            if await locator.count() > 0:
                is_vis = False
                try:
                    is_vis = await locator.first.is_visible()
                except (PlaywrightError, TimeoutError, RuntimeError):
                    is_vis = False
                if is_vis:
                    logger.warning("Amazon access restriction detected: %s", selector)
                    if selector == "#authportal-main-section":
                        raise ScrapingBlockedError("Amazon requires sign-in before collection.")
                    raise ScrapingBlockedError("Amazon bot challenge / CAPTCHA detected.")

        title = (await page.title()).lower()
        if "robot check" in title or "captcha" in title:
            raise ScrapingBlockedError("Amazon robot check detected in page title.")

        for selector in selectors.NOT_FOUND_MARKERS:
            locator = page.locator(selector)
            if await locator.count() > 0:
                raise PageNotFoundError("Amazon product not found (404/dog page).")

    # ------------------------------------------------------------------
    # Evidence capture
    # ------------------------------------------------------------------

    async def capture_evidence(self, page: Page, collector_name: str) -> EvidenceArtifactData:
        """Capture the current page's raw HTML, compute SHA-256 hash, and persist to evidence directory."""
        now = datetime.now(UTC)
        content = await page.content()
        encoded = content.encode("utf-8")
        if len(encoded) > self.settings.max_evidence_bytes:
            raise ScrapingError(
                ScrapeErrorCode.UNAVAILABLE, "Captured HTML exceeds configured evidence size limit"
            )
        content_hash = hashlib.sha256(encoded).hexdigest()
        size_bytes = len(encoded)

        storage_rel_path = f"{content_hash}.html"
        storage_abs_path = self.settings.evidence_dir / storage_rel_path
        storage_abs_path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic replacement keeps an older observation's content-addressed file intact
        # if a later capture of identical HTML fails while writing.
        def write() -> None:
            temporary: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    dir=storage_abs_path.parent, suffix=".tmp", delete=False
                ) as file:
                    temporary = Path(file.name)
                    file.write(encoded)
                os.replace(temporary, storage_abs_path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)

        await asyncio.to_thread(write)

        return EvidenceArtifactData(
            content_hash=content_hash,
            storage_path=str(storage_rel_path),
            content_size_bytes=size_bytes,
            source_url=page.url,
            collector=collector_name,
            captured_at=now,
            evidence_type="html",
        )

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    async def collect_product(
        self, asin: str, domain: str, requested_location: str | None = None
    ) -> tuple[Any, EvidenceArtifactData]:
        """Collect product detail data with raw evidence artifact."""
