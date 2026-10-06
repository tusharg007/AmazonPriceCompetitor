"""API -> real Chromium -> extraction -> database -> verified evidence integration.

Only network responses are intercepted; browser lifecycle and collector code are real.
"""

import os
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.collector.amazon import AmazonCollector
from app.worker.runner import CollectionWorker
from playwright.async_api import Route
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.tests.test_worker import enqueue
from tests.conftest import SAMPLE_BLOCK_HTML, SAMPLE_DOM_HTML, SAMPLE_JSONLD_HTML


class RoutedAmazonCollector(AmazonCollector):
    def __init__(self, settings, mode="jsonld"):
        super().__init__(settings)
        self.mode = mode
        self.urls = []
        self.browser_handle = None

    async def __aenter__(self):
        await super().__aenter__()
        self.browser_handle = self._browser
        context = await self._get_context("com")
        await context.route("**/*", self.respond)
        return self

    async def respond(self, route: Route):
        url = route.request.url
        self.urls.append(url)
        if "/s?" in url:
            if "page=2" in url and self.mode == "search_blocked":
                body = SAMPLE_BLOCK_HTML
            else:
                asin = "B000000003" if "page=2" in url else "B000000002"
                body = f'''<html><body>
                    <div data-component-type="s-search-result" data-asin="{asin}">
                      <h2><a href="/dp/{asin}"><span>Candidate headphones</span></a></h2>
                      <span class="a-price"><span class="a-offscreen">$99.00</span></span>
                    </div></body></html>'''
        elif self.mode == "blocked":
            body = SAMPLE_BLOCK_HTML
        elif self.mode == "not_found":
            body = "<html><body><div id='cs_404'>Page not found</div></body></html>"
        elif self.mode == "missing_title":
            body = "<html><body><div id='dp'>No product details</div></body></html>"
        elif self.mode == "dom" or "B00000000" in url:
            body = SAMPLE_DOM_HTML
        else:
            body = SAMPLE_JSONLD_HTML
        await route.fulfill(status=200, content_type="text/html", body=body)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,method,price", [("jsonld", "json_ld", "398"), ("dom", "structured_dom", "279")]
)
async def test_real_browser_worker_product_roundtrip(
    async_client, test_engine, test_settings, mode, method, price
):
    product, job = await enqueue(async_client)
    collector = RoutedAmazonCollector(test_settings, mode)
    async with CollectionWorker(
        async_sessionmaker(test_engine, expire_on_commit=False), test_settings, lambda _: collector
    ) as worker:
        assert await worker.run_once()
        assert not collector._contexts["com"].pages
    assert not collector.browser_handle.is_connected()
    assert collector._browser is None and collector._playwright is None
    detail = (await async_client.get(f"/api/jobs/{job['id']}")).json()
    assert detail["status"] == "succeeded", detail
    observation = (await async_client.get(f"/api/products/{product['id']}/observations")).json()[0]
    assert Decimal(observation["price_amount"]) == Decimal(price)
    assert observation["currency"] == "USD"
    assert observation["extraction_method"] == method
    assert observation["source_url"] == "https://www.amazon.com/dp/B09XS7JWHH"
    artifact = (
        await async_client.get(f"/api/evidence/{observation['evidence_artifact_id']}")
    ).json()
    assert artifact["content_hash"] == observation["evidence_id"]
    content = await async_client.get(f"/api/evidence/{artifact['id']}/content")
    assert content.status_code == 200 and b"Headphones" in content.content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,code",
    [("blocked", "blocked"), ("not_found", "not_found"), ("missing_title", "parse_error")],
)
async def test_real_browser_failures_publish_no_observation(
    async_client, test_engine, test_settings, mode, code
):
    product, job = await enqueue(async_client)
    collector = RoutedAmazonCollector(test_settings, mode)
    async with CollectionWorker(
        async_sessionmaker(test_engine, expire_on_commit=False), test_settings, lambda _: collector
    ) as worker:
        assert await worker.run_once()
    detail = (await async_client.get(f"/api/jobs/{job['id']}")).json()
    assert detail["status"] == "failed" and detail["error_code"] == code
    assert not collector.browser_handle.is_connected()
    assert (await async_client.get(f"/api/products/{product['id']}/observations")).json() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked", [False, True])
async def test_real_multi_page_search_retains_capture_provenance(
    async_client, test_engine, test_settings, blocked
):
    _, job = await enqueue(async_client, include=True)
    collector = RoutedAmazonCollector(test_settings, "search_blocked" if blocked else "jsonld")
    async with CollectionWorker(
        async_sessionmaker(test_engine, expire_on_commit=False), test_settings, lambda _: collector
    ) as worker:
        await worker.run_once()
    detail = (await async_client.get(f"/api/jobs/{job['id']}")).json()
    assert detail["status"] == ("partial" if blocked else "succeeded"), detail
    assert len(detail["result"]["candidates"]) == (1 if blocked else 2)
    assert len(detail["result"]["observation_ids"]) == (1 if blocked else 3)
    for candidate in detail["result"]["candidates"]:
        artifact = (
            await async_client.get(f"/api/evidence/{candidate['search_evidence_artifact_id']}")
        ).json()
        assert artifact["source_url"] == candidate["provenance"]["source_url"]
        # SQLite's DateTime storage returns naive UTC; PostgreSQL retains the offset.
        assert datetime.fromisoformat(artifact["captured_at"]).replace(
            tzinfo=UTC
        ) == datetime.fromisoformat(candidate["provenance"]["timestamp"]).replace(tzinfo=UTC)
        assert artifact["content_hash"] == candidate["provenance"]["evidence_id"]
    assert (await async_client.get("/api/products")).json()["total"] == 1


@pytest.mark.asyncio
async def test_atomic_capture_failure_preserves_previous_evidence(test_settings, monkeypatch):
    async with AmazonCollector(test_settings) as collector, collector.session("com") as page:
        await page.set_content(SAMPLE_JSONLD_HTML)
        first = await collector.capture_evidence(page, collector.COLLECTOR_NAME)
        path = test_settings.evidence_dir / first.storage_path
        original = path.read_bytes()

        def fail_replace(*args):
            raise OSError("Injected disk error")

        monkeypatch.setattr(os, "replace", fail_replace)
        with pytest.raises(OSError, match="disk error"):
            await collector.capture_evidence(page, collector.COLLECTOR_NAME)
        assert path.read_bytes() == original
        assert not list(test_settings.evidence_dir.glob("*.tmp"))
