"""Amazon page workflows using Selenium only; no HTTP-page fallback exists."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import quote_plus, urlparse

from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import WebDriverWait

from src.config import Settings
from src.models import (
    CollectionContext,
    ItemFailure,
    LocationStatus,
    ProductSnapshot,
    ScrapeErrorCode,
    ScrapeOutcome,
    SearchCandidate,
)
from src.scraping import selectors
from src.scraping.browser import chrome_session
from src.scraping.errors import ScrapingError
from src.scraping.parsers import (
    clean_text,
    parse_count,
    parse_decimal_price,
    parse_rating,
    product_asin_from_url,
)


def marketplace_url(domain: str) -> str:
    return f"https://www.amazon.{domain}"


def product_url(domain: str, asin: str) -> str:
    return f"{marketplace_url(domain)}/dp/{asin}"


def _first(driver: WebDriver, selector_group: tuple[str, ...], timeout: int) -> WebElement | None:
    wait = WebDriverWait(driver, timeout)
    for selector in selector_group:
        try:

            def locate(current: WebDriver, css_selector: str = selector) -> WebElement:
                return current.find_element(By.CSS_SELECTOR, css_selector)

            return wait.until(locate)
        except TimeoutException:
            continue
    return None


def _text(driver: WebDriver, selector_group: tuple[str, ...], timeout: int = 1) -> str | None:
    element = _first(driver, selector_group, timeout)
    return clean_text(element.text) if element else None


def _all_text(driver: WebDriver, selector_group: tuple[str, ...]) -> tuple[str, ...]:
    values: list[str] = []
    for selector in selector_group:
        for element in driver.find_elements(By.CSS_SELECTOR, selector):
            text = clean_text(element.text)
            if text and text not in values:
                values.append(text)
        if values:
            break
    return tuple(values)


def _check_page_state(driver: WebDriver) -> None:
    source = driver.page_source.lower()
    if any(driver.find_elements(By.CSS_SELECTOR, selector) for selector in selectors.BLOCK_MARKERS):
        raise ScrapingError(
            ScrapeErrorCode.BLOCKED, "Amazon presented a CAPTCHA, sign-in, or access block"
        )
    if "robot check" in driver.title.lower() or "enter the characters you see" in source:
        raise ScrapingError(ScrapeErrorCode.BLOCKED, "Amazon presented a bot-detection page")
    if any(
        driver.find_elements(By.CSS_SELECTOR, selector) for selector in selectors.NOT_FOUND_MARKERS
    ):
        raise ScrapingError(ScrapeErrorCode.NOT_FOUND, "Amazon did not return a product page")


def _is_allowed_url(url: str, domain: str) -> bool:
    host = urlparse(url).hostname or ""
    return host == f"www.amazon.{domain}" or host.endswith(f".amazon.{domain}")


def _set_location(
    driver: WebDriver, context: CollectionContext, settings: Settings
) -> tuple[LocationStatus, str | None]:
    if not context.requested_location:
        return LocationStatus.DEFAULT, _text(driver, selectors.LOCATION_DISPLAY, 1)
    trigger = _first(driver, selectors.LOCATION_TRIGGER, settings.element_timeout_seconds)
    if not trigger:
        return LocationStatus.UNSUPPORTED, None
    trigger.click()
    location_input = _first(driver, selectors.LOCATION_INPUT, settings.element_timeout_seconds)
    if not location_input:
        return LocationStatus.UNSUPPORTED, None
    location_input.clear()
    location_input.send_keys(context.requested_location)
    apply = _first(driver, selectors.LOCATION_APPLY, settings.element_timeout_seconds)
    if not apply:
        return LocationStatus.UNVERIFIED, None
    apply.click()
    observed = _text(driver, selectors.LOCATION_DISPLAY, settings.element_timeout_seconds)
    expected = context.geo_key.replace(" ", "")
    actual = (observed or "").upper().replace(" ", "")
    return (LocationStatus.VERIFIED if expected in actual else LocationStatus.UNVERIFIED), observed


class AmazonSeleniumScraper:
    """One scraper instance creates a fresh browser session for every public operation."""

    def __init__(self, settings: Settings, sleep: Callable[[float], None] = time.sleep) -> None:
        self.settings = settings
        self.sleep = sleep

    def scrape_product(self, context: CollectionContext) -> ScrapeOutcome:
        try:
            with chrome_session(self.settings, context.key.domain) as driver:
                driver.get(marketplace_url(context.key.domain))
                location_status, observed_location = _set_location(driver, context, self.settings)
                driver.get(product_url(context.key.domain, context.key.asin))
                self.sleep(self.settings.min_navigation_interval_seconds)
                _check_page_state(driver)
                title = _text(driver, selectors.TITLE, self.settings.element_timeout_seconds)
                if not title:
                    raise ScrapingError(ScrapeErrorCode.PARSE_ERROR, "Product title was not found")
                resolved_asin = product_asin_from_url(driver.current_url)
                if resolved_asin and resolved_asin != context.key.asin:
                    raise ScrapingError(
                        ScrapeErrorCode.VARIANT_MISMATCH, f"Amazon resolved to {resolved_asin}"
                    )
                price_text = _text(driver, selectors.PRICE, 2)
                price_amount, currency = parse_decimal_price(price_text, context.key.domain)
                image = _first(driver, selectors.IMAGE, 1)
                image_url = image.get_attribute("src") if image else None
                snapshot = ProductSnapshot(
                    context_id=context.id,
                    requested_asin=context.key.asin,
                    resolved_asin=resolved_asin or context.key.asin,
                    title=title,
                    canonical_url=driver.current_url
                    if _is_allowed_url(driver.current_url, context.key.domain)
                    else None,
                    captured_at=datetime.now(UTC),
                    capture_key=self._capture_key(driver.current_url, title, price_text),
                    domain=context.key.domain,
                    requested_location=context.requested_location,
                    observed_location=observed_location,
                    location_status=location_status,
                    brand=_text(driver, selectors.BRAND),
                    price_amount=price_amount,
                    price_text=price_text,
                    currency=currency,
                    price_kind="current" if price_text else None,
                    availability=_text(driver, selectors.AVAILABILITY),
                    rating=parse_rating(_text(driver, selectors.RATING)),
                    rating_count=parse_count(_text(driver, selectors.RATING_COUNT)),
                    images=(image_url,) if image_url else (),
                    categories=_all_text(driver, selectors.BREADCRUMBS),
                    category_path=_all_text(driver, selectors.BREADCRUMBS),
                )
                if (
                    location_status in {LocationStatus.UNVERIFIED, LocationStatus.UNSUPPORTED}
                    and context.requested_location
                ):
                    return ScrapeOutcome(
                        snapshot=snapshot,
                        code=ScrapeErrorCode.LOCATION_UNVERIFIED,
                        message="Price was captured but delivery location could not be verified",
                    )
                return ScrapeOutcome(snapshot=snapshot)
        except ScrapingError as exc:
            return ScrapeOutcome(code=exc.code, message=str(exc))
        except TimeoutException:
            return ScrapeOutcome(code=ScrapeErrorCode.TIMEOUT, message="Amazon page timed out")
        except WebDriverException as exc:
            message = getattr(exc, "msg", None) or str(exc)
            return ScrapeOutcome(
                code=ScrapeErrorCode.BROWSER_ERROR, message=f"Browser error: {message[:240]}"
            )

    def discover(
        self, context: CollectionContext, query: str, pages: int
    ) -> tuple[list[SearchCandidate], list[ItemFailure]]:
        candidates: list[SearchCandidate] = []
        failures: list[ItemFailure] = []
        seen: set[str] = set()
        try:
            with chrome_session(self.settings, context.key.domain) as driver:
                driver.get(marketplace_url(context.key.domain))
                status, _ = _set_location(driver, context, self.settings)
                if context.requested_location and status != LocationStatus.VERIFIED:
                    return [], [
                        ItemFailure(
                            None,
                            ScrapeErrorCode.LOCATION_UNVERIFIED,
                            "Cannot verify delivery location",
                        )
                    ]
                for page in range(1, pages + 1):
                    driver.get(
                        f"{marketplace_url(context.key.domain)}/s?k={quote_plus(query)}&page={page}"
                    )
                    self.sleep(self.settings.min_navigation_interval_seconds)
                    _check_page_state(driver)
                    cards = driver.find_elements(By.CSS_SELECTOR, selectors.SEARCH_CARD)
                    if not cards:
                        break
                    page_asins: set[str] = set()
                    for card in cards:
                        asin = (card.get_attribute("data-asin") or "").strip().upper()
                        if len(asin) != 10 or asin == context.key.asin or asin in seen:
                            continue
                        title = None
                        for selector in selectors.SEARCH_TITLE:
                            found = card.find_elements(By.CSS_SELECTOR, selector)
                            if found:
                                title = clean_text(found[0].text)
                                break
                        link = card.find_elements(By.CSS_SELECTOR, selectors.SEARCH_LINK)
                        url = link[0].get_attribute("href") if link else None
                        sponsored = "sponsored" in card.text.lower()
                        seen.add(asin)
                        page_asins.add(asin)
                        candidates.append(
                            SearchCandidate(
                                asin=asin,
                                title=title,
                                rank=len(candidates) + 1,
                                query=query,
                                sponsored=sponsored,
                                canonical_url=url,
                            )
                        )
                    if not page_asins:
                        break
                    next_buttons = driver.find_elements(By.CSS_SELECTOR, selectors.NEXT_PAGE[0])
                    if (
                        page >= pages
                        or not next_buttons
                        or "disabled" in (next_buttons[0].get_attribute("class") or "")
                    ):
                        break
        except ScrapingError as exc:
            failures.append(ItemFailure(None, exc.code, str(exc)))
        except TimeoutException:
            failures.append(ItemFailure(None, ScrapeErrorCode.TIMEOUT, "Amazon search timed out"))
        except WebDriverException as exc:
            message = getattr(exc, "msg", None) or str(exc)
            failures.append(
                ItemFailure(None, ScrapeErrorCode.BROWSER_ERROR, f"Browser error: {message[:240]}")
            )
        return candidates, failures

    @staticmethod
    def _capture_key(url: str, title: str, price: str | None) -> str:
        # Job-level context and timestamp make intentional refreshes new snapshots while retries stay idempotent.
        material = f"{url}|{title}|{price}|{datetime.now(UTC).replace(microsecond=0).isoformat()}"
        return hashlib.sha256(material.encode()).hexdigest()
