"""Tests for BrowserCollector abstraction and AmazonCollector workflow."""

import asyncio
import json

import pytest
from app.collector.amazon import AmazonCollector
from app.collector.base import PageNotFoundError, ScrapingBlockedError
from playwright.async_api import async_playwright

from tests.conftest import SAMPLE_BLOCK_HTML, SAMPLE_JSONLD_HTML


@pytest.mark.asyncio
async def test_bot_challenge_detection(test_settings) -> None:
    collector = AmazonCollector(test_settings)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(SAMPLE_BLOCK_HTML)

        with pytest.raises(ScrapingBlockedError, match="challenge"):
            await collector.check_page_state(page)

        await browser.close()


@pytest.mark.asyncio
async def test_page_not_found_detection(test_settings) -> None:
    collector = AmazonCollector(test_settings)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content("<div id='cs_404'>Page not found</div>")

        with pytest.raises(PageNotFoundError, match="not found"):
            await collector.check_page_state(page)

        await browser.close()


@pytest.mark.asyncio
async def test_sign_in_classification_and_hidden_challenge_are_not_false_captchas(test_settings):
    collector = AmazonCollector(test_settings)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content("<section id='authportal-main-section'>Sign in</section>")
            with pytest.raises(ScrapingBlockedError, match="requires sign-in"):
                await collector.check_page_state(page)
            await page.set_content(
                "<input id='captchacharacters' style='display:none'><div id='productTitle'>Listing</div>"
            )
            await collector.check_page_state(page)
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_collector_session_lifecycle(test_settings) -> None:
    # C-2 fix: Collector must be used as async context manager to initialise browser
    async with AmazonCollector(test_settings) as collector, collector.session("com") as page:
        await page.set_content(SAMPLE_JSONLD_HTML)
        title = await page.title()
        assert "Sony" in title

        # Verify stealth script injected
        webdriver_flag = await page.evaluate("navigator.webdriver")
        assert webdriver_flag is None


@pytest.mark.asyncio
async def test_collector_reuses_context_across_pages(test_settings) -> None:
    """Verify that a second session() call for the same domain reuses the same BrowserContext."""
    async with AmazonCollector(test_settings) as collector:
        async with collector.session("com") as page1:
            await page1.set_content("<html><body>Page 1</body></html>")
            ctx_id_1 = id(collector._contexts.get("com"))

        async with collector.session("com") as page2:
            await page2.set_content("<html><body>Page 2</body></html>")
            ctx_id_2 = id(collector._contexts.get("com"))

        # Same context object must be reused — not a new Chromium process per call
        assert ctx_id_1 == ctx_id_2, "BrowserContext should be reused across session() calls"


@pytest.mark.asyncio
async def test_marketplace_contexts_keep_cookies_isolated(test_settings) -> None:
    async with AmazonCollector(test_settings) as collector:
        async with collector.session("com") as page:
            com_context = page.context
            await com_context.add_cookies(
                [{"name": "location", "value": "US", "domain": ".amazon.com", "path": "/"}]
            )
        async with collector.session("in") as page:
            assert page.context is not com_context
            assert await page.context.cookies() == []
        with pytest.raises(ValueError, match="marketplace"):
            async with collector.session("../../outside"):
                pytest.fail("Unsupported domain must be rejected before creating a context")
        assert len(collector._contexts) == 2
    assert not collector._contexts
    assert collector._browser is None and collector._playwright is None
    # State survives collector lifetimes but stays in its marketplace's context.
    async with AmazonCollector(test_settings) as collector, collector.session("com") as page:
        assert (await page.context.cookies())[0]["value"] == "US"


def test_storage_state_from_other_marketplace_is_rejected(test_settings, tmp_path) -> None:
    collector = AmazonCollector(test_settings)
    state = tmp_path / "storage_state.json"
    state.write_text(
        json.dumps({"cookies": [{"domain": ".amazon.in"}], "origins": []}), encoding="utf-8"
    )
    assert collector._load_storage_state(tmp_path, "com") is None
    state.write_text(
        json.dumps({"cookies": [], "origins": [{"origin": "https://amazon.com.evil.example"}]}),
        encoding="utf-8",
    )
    assert collector._load_storage_state(tmp_path, "com") is None
    state.write_text("not json", encoding="utf-8")
    assert collector._load_storage_state(tmp_path, "com") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_real_browser_disconnects_after_exception_or_cancellation(
    test_settings, cancelled
) -> None:
    collector = AmazonCollector(test_settings)
    failure = asyncio.CancelledError() if cancelled else RuntimeError("collection failed")
    with pytest.raises(type(failure)):
        async with collector, collector.session("com") as page:
            browser = collector._browser
            raise failure
    assert page.is_closed()
    assert browser is not None and not browser.is_connected()
    assert collector._browser is None and collector._playwright is None
