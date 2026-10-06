"""Amazon-specific Playwright collector with structured JSON-LD and DOM extraction."""

from __future__ import annotations

import json
import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote_plus, urljoin

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page

from app.collector import selectors
from app.collector.base import BrowserCollector, EvidenceArtifactData
from app.collector.parsers import (
    clean_text,
    normalized_query,
    parse_count,
    parse_decimal_price,
    parse_rating,
    product_asin_from_url,
)
from app.models.schemas import (
    ExtractedProduct,
    ExtractedSearchCandidate,
    ProductCreate,
    ProvenanceMetadata,
)

logger = logging.getLogger(__name__)


def marketplace_url(domain: str) -> str:
    """Build Amazon base URL for a domain."""
    return f"https://www.amazon.{domain}"


def product_url(domain: str, asin: str) -> str:
    """Build Amazon product URL for an ASIN."""
    return f"https://www.amazon.{domain}/dp/{asin}"


class AmazonCollector(BrowserCollector):
    """Playwright-based collector for Amazon product pages and search discovery."""

    COLLECTOR_NAME = "playwright_amazon"

    async def _extract_json_ld(self, page: Page) -> dict[str, Any] | None:
        """Extract structured Schema.org Product data from JSON-LD script tags."""
        script_locators = page.locator("script[type='application/ld+json']")
        count = await script_locators.count()

        for idx in range(count):
            try:
                raw_text = await script_locators.nth(idx).text_content()
                if not raw_text or not raw_text.strip():
                    continue
                data = json.loads(raw_text)

                # JSON-LD can be a list or single dict with @graph
                items: list[dict[str, Any]] = []
                if isinstance(data, list):
                    items = [d for d in data if isinstance(d, dict)]
                elif isinstance(data, dict):
                    if "@graph" in data and isinstance(data["@graph"], list):
                        items = [d for d in data["@graph"] if isinstance(d, dict)]
                    else:
                        items = [data]

                for item in items:
                    item_types = item.get("@type", [])
                    if isinstance(item_types, str):
                        item_types = [item_types]
                    if isinstance(item_types, list) and any(
                        str(t).lower() in ("product", "individualproduct") for t in item_types
                    ):
                        return item
            except (PlaywrightError, KeyError, ValueError, TypeError) as exc:
                logger.debug("Failed parsing JSON-LD script %d: %s", idx, exc)

        return None

    async def _query_first_text(
        self, page: Page | Locator, selector_group: tuple[str, ...]
    ) -> str | None:
        """Iterate selector chain and return the first matched non-empty text content."""
        timeout_ms = self.settings.element_timeout_seconds * 1000
        for selector in selector_group:
            locator = page.locator(selector)
            try:
                if await locator.count() > 0:
                    text = await locator.first.text_content(timeout=timeout_ms)
                    cleaned = clean_text(text)
                    if cleaned:
                        return cleaned
            except (PlaywrightError, TimeoutError):
                continue
        return None

    async def _query_attribute(
        self, page: Page, selector_group: tuple[str, ...], attr_name: str
    ) -> str | None:
        """Iterate selector chain and return first matched attribute."""
        timeout_ms = self.settings.element_timeout_seconds * 1000
        for selector in selector_group:
            locator = page.locator(selector)
            try:
                if await locator.count() > 0:
                    val = await locator.first.get_attribute(attr_name, timeout=timeout_ms)
                    if val and val.strip():
                        return val.strip()
            except (PlaywrightError, TimeoutError):
                continue
        return None

    async def _extract_structured_dom(self, page: Page, domain: str) -> dict[str, Any]:
        """Extract product attributes directly from structured DOM elements."""
        title = await self._query_first_text(page, selectors.TITLE)
        raw_price = await self._query_first_text(page, selectors.PRICE)
        price_amount, currency = parse_decimal_price(raw_price, domain)

        brand = await self._query_first_text(page, selectors.BRAND)
        if brand:
            brand = re.sub(r"(?i)^visit the\s+", "", brand)
            brand = re.sub(r"(?i)\s+store$", "", brand)
            brand = re.sub(r"(?i)^brand:\s*", "", brand).strip()
            if not brand:
                brand = None

        rating_text = await self._query_first_text(page, selectors.RATING)
        rating = parse_rating(rating_text)

        rating_count_text = await self._query_first_text(page, selectors.RATING_COUNT)
        rating_count = parse_count(rating_count_text)

        availability = await self._query_first_text(page, selectors.AVAILABILITY)
        image_src = await self._query_attribute(page, selectors.IMAGE, "src")

        # Breadcrumbs
        breadcrumbs: list[str] = []
        for selector in selectors.BREADCRUMBS:
            links = page.locator(selector)
            cnt = await links.count()
            if cnt > 0:
                for i in range(cnt):
                    crumb = await links.nth(i).text_content()
                    cleaned_crumb = clean_text(crumb)
                    if cleaned_crumb and cleaned_crumb not in breadcrumbs:
                        breadcrumbs.append(cleaned_crumb)
                if breadcrumbs:
                    break

        return {
            "title": title,
            "brand": brand,
            "price_amount": price_amount,
            "price_text": raw_price,
            "currency": currency,
            "rating": rating,
            "rating_count": rating_count,
            "availability": availability,
            "images": [image_src] if image_src else [],
            "categories": breadcrumbs,
        }

    async def _click_first_match(self, page: Page, selector_group: tuple[str, ...]) -> bool:
        """Click the first visible element matching any selector in the group. Returns True on success."""
        for selector in selector_group:
            locator = page.locator(selector)
            try:
                if await locator.count() > 0 and await locator.first.is_visible():
                    await locator.first.click(timeout=self.settings.element_timeout_seconds * 1000)
                    return True
            except (PlaywrightError, TimeoutError):
                continue
        return False

    async def _set_delivery_location(self, page: Page, requested_location: str) -> str:
        """Inject geographic postal code into Amazon GLUX location modal.

        H-3: Iterates all fallback selectors in LOCATION_TRIGGER / LOCATION_INPUT /
        LOCATION_APPLY chains instead of blindly indexing [0].
        """
        try:
            triggered = await self._click_first_match(page, selectors.LOCATION_TRIGGER)
            if not triggered:
                return "unverified"

            # Fill input using fallback chain
            filled = False
            for selector in selectors.LOCATION_INPUT:
                try:
                    input_box = page.locator(selector).first
                    await input_box.fill(
                        requested_location, timeout=self.settings.element_timeout_seconds * 1000
                    )
                    filled = True
                    break
                except (PlaywrightError, TimeoutError):
                    continue
            if not filled:
                return "unverified"

            applied = await self._click_first_match(page, selectors.LOCATION_APPLY)
            if applied:
                normalized = "".join(requested_location.split()).casefold()
                for selector in selectors.LOCATION_DISPLAY:
                    try:
                        await (
                            page.locator(selector)
                            .filter(
                                has_text=re.compile(re.escape(requested_location), re.IGNORECASE)
                            )
                            .first.wait_for(
                                state="visible",
                                timeout=self.settings.element_timeout_seconds * 1000,
                            )
                        )
                        displayed = await self._query_first_text(page, (selector,))
                        if displayed and normalized in "".join(displayed.split()).casefold():
                            return "verified"
                    except (PlaywrightError, TimeoutError):
                        continue

        except (PlaywrightError, TimeoutError, RuntimeError) as exc:
            logger.warning("Could not set delivery location '%s': %s", requested_location, exc)
        return "unverified"

    async def collect_product(
        self, asin: str, domain: str, requested_location: str | None = None
    ) -> tuple[ExtractedProduct, EvidenceArtifactData]:
        """Navigate to product page, capture raw evidence, and extract structured product with provenance."""
        validated = ProductCreate(asin=asin, domain=domain, requested_location=requested_location)
        asin, domain = validated.asin, validated.domain
        target_url = product_url(domain, asin)

        async with self.session(domain) as page:
            await self._enforce_pacing()
            await page.goto(target_url, wait_until="domcontentloaded")
            await self.check_page_state(page)

            location_status = "default"
            if requested_location:
                location_status = await self._set_delivery_location(page, requested_location)
                await self.check_page_state(page)
            resolved_asin = product_asin_from_url(page.url)
            if resolved_asin is not None and resolved_asin != asin:
                raise ValueError("Amazon redirected to a different product ASIN.")

            # Capture immutable raw HTML evidence artifact
            evidence = await self.capture_evidence(page, self.COLLECTOR_NAME)

            # 1. First priority: Structured JSON-LD microdata
            json_ld = await self._extract_json_ld(page)

            # 2. Structured DOM fallback & enrichment
            dom_data = await self._extract_structured_dom(page, domain)

            # Determine extraction method and merge data
            extraction_method = "structured_dom"
            title: str | None = dom_data.get("title")
            brand: str | None = dom_data.get("brand")
            price_amount: Decimal | None = dom_data.get("price_amount")
            price_text: str | None = dom_data.get("price_text")
            currency: str | None = dom_data.get("currency")
            rating: float | None = dom_data.get("rating")
            rating_count: int | None = dom_data.get("rating_count")
            availability: str | None = dom_data.get("availability")
            images: list[str] = dom_data.get("images", [])
            categories: list[str] = dom_data.get("categories", [])

            if json_ld:
                json_ld_used = False
                if json_ld.get("name"):
                    title = clean_text(json_ld["name"])
                    json_ld_used = True

                if json_ld.get("brand"):
                    brand_val = json_ld["brand"]
                    if isinstance(brand_val, dict):
                        brand_name = brand_val.get("name")
                    elif isinstance(brand_val, str):
                        brand_name = brand_val
                    else:
                        brand_name = None
                    if isinstance(brand_name, str) and clean_text(brand_name):
                        brand = clean_text(brand_name)
                        json_ld_used = True

                offers = json_ld.get("offers")
                if isinstance(offers, list) and offers:
                    offers = offers[0]
                if isinstance(offers, dict):
                    if offers.get("price") is not None:
                        try:
                            structured_price = Decimal(str(offers["price"]))
                            if structured_price.is_finite() and structured_price >= 0:
                                price_amount = structured_price
                                price_text = str(offers["price"])
                                _, inferred_currency = parse_decimal_price(price_text, domain)
                                currency = str(
                                    offers.get("priceCurrency") or inferred_currency
                                ).upper()
                                json_ld_used = True
                        except (InvalidOperation, ValueError, TypeError):
                            pass
                    if offers.get("availability"):
                        avail_str = str(offers["availability"])
                        availability = "In Stock" if "InStock" in avail_str else "Out of Stock"
                        json_ld_used = True

                agg_rating = json_ld.get("aggregateRating")
                if isinstance(agg_rating, dict):
                    if agg_rating.get("ratingValue") is not None:
                        structured_rating = parse_rating(str(agg_rating["ratingValue"]))
                        if structured_rating is not None:
                            rating = structured_rating
                            json_ld_used = True
                    if agg_rating.get("reviewCount") is not None:
                        structured_count = parse_count(str(agg_rating["reviewCount"]))
                        if structured_count is not None:
                            rating_count = structured_count
                            json_ld_used = True

                if json_ld.get("image"):
                    img = json_ld["image"]
                    if isinstance(img, str) and img not in images:
                        images.insert(0, img)
                    elif isinstance(img, list):
                        images = [i for i in img if isinstance(i, str)] + images

                if json_ld_used and dom_data.get("price_amount") is not None:
                    extraction_method = "json_ld_dom_hybrid"
                elif json_ld_used:
                    extraction_method = "json_ld"

            provenance = ProvenanceMetadata(
                source_url=page.url,
                timestamp=evidence.captured_at,
                collector=self.COLLECTOR_NAME,
                extraction_method=extraction_method,
                evidence_id=evidence.content_hash,
            )

            product = ExtractedProduct(
                asin=asin,
                domain=domain,
                title=title,
                brand=brand,
                price_amount=price_amount,
                price_text=price_text,
                currency=currency,
                availability=availability,
                rating=rating,
                rating_count=rating_count,
                location_status=location_status,
                canonical_url=page.url,
                categories=categories,
                images=images,
                raw_metadata={"json_ld": json_ld} if json_ld else {},
                provenance=provenance,
            )

            return product, evidence

    async def search_competitors(
        self, query: str, domain: str, max_pages: int = 1
    ) -> tuple[list[ExtractedSearchCandidate], EvidenceArtifactData]:
        """Perform Amazon search and extract competitor listing candidates with provenance."""
        domain = ProductCreate.validate_domain(domain)
        q = quote_plus(normalized_query(query))
        base_search_url = f"{marketplace_url(domain)}/s?k={q}"

        candidates: list[ExtractedSearchCandidate] = []
        latest_evidence: EvidenceArtifactData | None = None

        async with self.session(domain) as page:
            for page_num in range(1, max_pages + 1):
                url = f"{base_search_url}&page={page_num}" if page_num > 1 else base_search_url
                await self._enforce_pacing()
                await page.goto(url, wait_until="domcontentloaded")
                await self.check_page_state(page)

                evidence = await self.capture_evidence(page, self.COLLECTOR_NAME)
                latest_evidence = evidence

                cards: Locator = page.locator(selectors.SEARCH_CARD)
                card_count = await cards.count()

                for rank_idx in range(card_count):
                    card = cards.nth(rank_idx)
                    card_asin = await card.get_attribute("data-asin")
                    if not card_asin or len(card_asin) != 10:
                        continue

                    # Title & link
                    title = await self._query_first_text(card, selectors.SEARCH_TITLE)
                    if not title:
                        continue

                    link_elem = card.locator(selectors.SEARCH_LINK)
                    detail_path = (
                        await link_elem.first.get_attribute("href")
                        if await link_elem.count() > 0
                        else ""
                    )
                    detail_url = (
                        urljoin(marketplace_url(domain), detail_path)
                        if detail_path
                        else product_url(domain, card_asin)
                    )

                    # Price
                    price_text = await self._query_first_text(card, selectors.SEARCH_PRICE)
                    price_amount, currency = parse_decimal_price(price_text, domain)

                    # Rating
                    rating_text = await self._query_first_text(card, selectors.SEARCH_RATING)
                    rating = parse_rating(rating_text)

                    # Rating count
                    count_text = await self._query_first_text(card, selectors.SEARCH_RATING_COUNT)
                    rating_count = parse_count(count_text)

                    # Sponsored flag
                    sponsored_badge = card.locator(
                        "div.puis-sponsored-label-text, span:has-text('Sponsored')"
                    )
                    sponsored = await sponsored_badge.count() > 0

                    provenance = ProvenanceMetadata(
                        source_url=page.url,
                        timestamp=evidence.captured_at,
                        collector=self.COLLECTOR_NAME,
                        extraction_method="search_card_dom",
                        evidence_id=evidence.content_hash,
                    )

                    candidate = ExtractedSearchCandidate(
                        asin=card_asin,
                        title=title,
                        price_amount=price_amount,
                        price_text=price_text,
                        currency=currency,
                        rating=rating,
                        rating_count=rating_count,
                        rank=len(candidates) + 1,
                        sponsored=sponsored,
                        detail_url=detail_url,
                        provenance=provenance,
                    )
                    candidates.append(candidate)

        if not latest_evidence:
            raise RuntimeError("No evidence captured during search execution.")

        return candidates, latest_evidence
