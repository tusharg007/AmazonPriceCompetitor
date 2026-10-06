"""Tests for structured JSON-LD and DOM extraction without network calls."""

import hashlib
import json
from decimal import Decimal

import pytest
from app.collector import selectors
from app.collector.amazon import AmazonCollector
from playwright.async_api import async_playwright

from tests.conftest import SAMPLE_DOM_HTML, SAMPLE_JSONLD_HTML, SAMPLE_SEARCH_HTML


@pytest.mark.asyncio
async def test_extract_jsonld_product(test_settings) -> None:
    collector = AmazonCollector(test_settings)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(SAMPLE_JSONLD_HTML)

        # 1. Test raw JSON-LD extraction
        json_ld = await collector._extract_json_ld(page)
        assert json_ld is not None
        assert json_ld.get("name") == "Sony WH-1000XM5 Noise Canceling Headphones"
        assert json_ld.get("brand", {}).get("name") == "Sony"
        assert json_ld.get("offers", {}).get("price") == "398.00"
        assert json_ld.get("offers", {}).get("priceCurrency") == "USD"
        assert json_ld.get("aggregateRating", {}).get("ratingValue") == "4.6"
        assert json_ld.get("aggregateRating", {}).get("reviewCount") == "12845"

        # 2. Test capture evidence
        evidence = await collector.capture_evidence(page, "test_collector")
        assert evidence.content_hash is not None
        assert evidence.storage_path.endswith(".html")
        assert (test_settings.evidence_dir / evidence.storage_path).exists()

        await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("price", ["398.00", "0.00", "NaN", "-1", "not a price"])
async def test_collect_product_prefers_valid_jsonld_and_retains_dom_fallback(
    test_settings, price
) -> None:
    data = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": ["Thing", "Product"],
                "name": "Structured product title",
                "offers": {"price": price, "priceCurrency": "EUR"},
                "aggregateRating": {"ratingValue": "9", "reviewCount": "1.5K"},
            }
        ],
    }
    html = SAMPLE_DOM_HTML.replace(
        "</head>", f"<script type='application/ld+json'>{json.dumps(data)}</script></head>"
    )
    async with AmazonCollector(test_settings) as collector:
        context = await collector._get_context("com")
        await context.route(
            "**/*", lambda route: route.fulfill(body=html, content_type="text/html")
        )
        product, evidence = await collector.collect_product("B09XS7JWHH", "com")
    assert product.title == "Structured product title"
    assert product.rating == 4.5  # Invalid JSON-LD rating must not erase a valid DOM rating.
    assert product.rating_count == 1500
    if price in ("398.00", "0.00"):
        assert product.price_amount == Decimal(price) and product.currency == "EUR"
    else:
        assert product.price_amount == Decimal("279.00") and product.currency == "USD"
    stored = (test_settings.evidence_dir / evidence.storage_path).read_bytes()
    assert hashlib.sha256(stored).hexdigest() == evidence.content_hash
    assert evidence.content_size_bytes == len(stored)
    assert product.provenance.evidence_id == evidence.content_hash
    assert product.provenance.source_url == evidence.source_url
    assert product.provenance.timestamp == evidence.captured_at
    assert product.provenance.extraction_method == "json_ld_dom_hybrid"


@pytest.mark.asyncio
async def test_selector_chains_are_valid_and_brand_fallback_reads_value(test_settings) -> None:
    async with AmazonCollector(test_settings) as collector, collector.session("com") as page:
        await page.set_content(
            "<div id='productOverview_feature_div'><table><tr><th>Brand</th><td>Sony</td></tr></table></div>"
        )
        for name, group in vars(selectors).items():
            if name.isupper():
                for selector in group if isinstance(group, tuple) else (group,):
                    await page.locator(selector).count()
        assert await collector._query_first_text(page, selectors.BRAND) == "Sony"


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmed", [True, False])
async def test_location_fallback_requires_actual_display_confirmation(
    test_settings, confirmed
) -> None:
    html = """<button id='nav-global-location-popover-link' onclick="document.getElementById('modal').hidden=false">Location</button>
    <div id='modal' hidden><input id='GLUXZipUpdateInput' disabled>
    <input name='location'><button id='GLUXZipUpdate-announce' onclick="document.getElementById('nav-global-location-slot').textContent='REPLACE'">Apply</button></div>
    <span id='nav-global-location-slot'>Deliver to default</span>"""
    html = html.replace("REPLACE", "Deliver to 90210" if confirmed else "Deliver to default")
    async with AmazonCollector(test_settings) as collector, collector.session("com") as page:
        await page.set_content(html)
        status = await collector._set_delivery_location(page, "90210")
        assert status == ("verified" if confirmed else "unverified")


@pytest.mark.asyncio
async def test_search_uses_selector_fallbacks_and_paces_every_page(
    test_settings, monkeypatch
) -> None:
    from unittest.mock import AsyncMock

    html = SAMPLE_SEARCH_HTML.replace("a-icon-star-small", "a-icon-star")
    html = html.replace(
        '<h2><a href="/dp/B09XS7JWHH"><span>Sony WH-1000XM5 Headphones</span></a></h2>',
        '<a href="/dp/B09XS7JWHH"><h2>Sony WH-1000XM5 Headphones</h2></a>',
    )
    html = html.replace('aria-label="12,845 ratings"', 'class="a-link-normal"')
    html = html.replace(
        '<span class="a-link-normal">12,845</span>',
        '<span class="a-size-small"><span class="a-link-normal">12.5K ratings</span></span>',
    )
    async with AmazonCollector(test_settings) as collector:
        context = await collector._get_context("com")
        await context.route(
            "**/*", lambda route: route.fulfill(body=html, content_type="text/html")
        )
        paced = AsyncMock()
        monkeypatch.setattr(collector, "_enforce_pacing", paced)
        candidates, _ = await collector.search_competitors("headphones", "com", max_pages=2)
        assert paced.await_count == 2
        assert candidates[0].rating == 4.6
        assert candidates[0].rating_count == 12500
        assert candidates[0].detail_url == "https://www.amazon.com/dp/B09XS7JWHH"


@pytest.mark.asyncio
async def test_extract_structured_dom_product(test_settings) -> None:
    collector = AmazonCollector(test_settings)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(SAMPLE_DOM_HTML)

        dom_data = await collector._extract_structured_dom(page, "com")
        assert "Bose QuietComfort 45" in dom_data["title"]
        assert dom_data["brand"] == "Bose"
        assert dom_data["price_amount"] == Decimal("279.00")
        assert dom_data["currency"] == "USD"
        assert dom_data["rating"] == 4.5
        assert dom_data["rating_count"] == 8320
        assert dom_data["availability"] == "In Stock"
        assert "https://m.media-amazon.com/images/I/bose_qc45.jpg" in dom_data["images"]
        assert "Electronics" in dom_data["categories"]

        await browser.close()


@pytest.mark.asyncio
async def test_search_candidates_extraction_from_dom(test_settings) -> None:
    collector = AmazonCollector(test_settings)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(SAMPLE_SEARCH_HTML)

        evidence = await collector.capture_evidence(page, collector.COLLECTOR_NAME)
        assert evidence.content_hash is not None
        cards = page.locator("div[data-component-type='s-search-result']")
        count = await cards.count()
        assert count == 2

        # Card 1 (Organic)
        c1 = cards.nth(0)
        assert await c1.get_attribute("data-asin") == "B09XS7JWHH"
        title1 = await c1.locator("h2 a span").first.text_content()
        assert "Sony WH-1000XM5" in title1

        # Card 2 (Sponsored)
        c2 = cards.nth(1)
        assert await c2.get_attribute("data-asin") == "B098FKXT8L"
        is_sponsored = await c2.locator(".puis-sponsored-label-text").count() > 0
        assert is_sponsored is True

        await browser.close()
