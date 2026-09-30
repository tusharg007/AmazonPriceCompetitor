"""Amazon page workflows using Selenium only; no HTTP-page fallback exists."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from urllib.parse import quote_plus, urlparse

from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
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


def _element_text(element: WebElement) -> str | None:
    return (
        clean_text(element.text)
        or clean_text(element.get_attribute("textContent"))
        or clean_text(element.get_attribute("aria-label"))
    )


def _text(driver: WebDriver, selector_group: tuple[str, ...], timeout: int = 1) -> str | None:
    for selector in selector_group:
        try:

            def read_text(current: WebDriver, css_selector: str = selector) -> str | None:
                return _element_text(current.find_element(By.CSS_SELECTOR, css_selector))

            return WebDriverWait(
                driver,
                timeout,
                ignored_exceptions=(NoSuchElementException, StaleElementReferenceException),
            ).until(read_text)
        except TimeoutException:
            continue
    return None


def _attribute(
    driver: WebDriver, selector_group: tuple[str, ...], name: str, timeout: int = 1
) -> str | None:
    for selector in selector_group:
        try:

            def read_attribute(current: WebDriver, css_selector: str = selector) -> str | None:
                return current.find_element(By.CSS_SELECTOR, css_selector).get_attribute(name)

            return WebDriverWait(
                driver,
                timeout,
                ignored_exceptions=(NoSuchElementException, StaleElementReferenceException),
            ).until(read_attribute)
        except TimeoutException:
            continue
    return None


def _click(driver: WebDriver, selector_group: tuple[str, ...], timeout: int) -> bool:
    for selector in selector_group:
        try:

            def click(current: WebDriver, css_selector: str = selector) -> bool:
                current.find_element(By.CSS_SELECTOR, css_selector).click()
                return True

            WebDriverWait(
                driver,
                timeout,
                ignored_exceptions=(NoSuchElementException, StaleElementReferenceException),
            ).until(click)
            return True
        except TimeoutException:
            continue
    return False


def _fill(driver: WebDriver, selector_group: tuple[str, ...], value: str, timeout: int) -> bool:
    for selector in selector_group:
        try:

            def fill(current: WebDriver, css_selector: str = selector) -> bool:
                element = current.find_element(By.CSS_SELECTOR, css_selector)
                element.clear()
                element.send_keys(value)
                return True

            WebDriverWait(
                driver,
                timeout,
                ignored_exceptions=(NoSuchElementException, StaleElementReferenceException),
            ).until(fill)
            return True
        except TimeoutException:
            continue
    return False


def _all_text(driver: WebDriver, selector_group: tuple[str, ...]) -> tuple[str, ...]:
    for selector in selector_group:
        for _ in range(3):
            try:
                values: list[str] = []
                for element in driver.find_elements(By.CSS_SELECTOR, selector):
                    text = clean_text(element.text)
                    if text and text not in values:
                        values.append(text)
                if values:
                    return tuple(values)
                break
            except StaleElementReferenceException:
                continue
    return ()


def _check_page_state(driver: WebDriver) -> None:
    if any(
        element.is_displayed()
        for selector in selectors.BLOCK_MARKERS
        for element in driver.find_elements(By.CSS_SELECTOR, selector)
    ):
        raise ScrapingError(
            ScrapeErrorCode.BLOCKED, "Amazon presented a CAPTCHA, sign-in, or access block"
        )
    if "robot check" in driver.title.lower():
        raise ScrapingError(ScrapeErrorCode.BLOCKED, "Amazon presented a bot-detection page")
    if any(
        driver.find_elements(By.CSS_SELECTOR, selector) for selector in selectors.NOT_FOUND_MARKERS
    ):
        raise ScrapingError(ScrapeErrorCode.NOT_FOUND, "Amazon did not return a product page")


def _is_allowed_url(url: str, domain: str) -> bool:
    host = urlparse(url).hostname or ""
    return host == f"amazon.{domain}" or host.endswith(f".amazon.{domain}")


def _set_location(
    driver: WebDriver, context: CollectionContext, settings: Settings
) -> tuple[LocationStatus, str | None]:
    if not context.requested_location:
        return LocationStatus.DEFAULT, _text(driver, selectors.LOCATION_DISPLAY, 1)
    observed = _text(driver, selectors.LOCATION_DISPLAY, 1)
    if observed and context.geo_key.replace(" ", "") in observed.upper().replace(" ", ""):
        return LocationStatus.VERIFIED, observed
    if not _click(driver, selectors.LOCATION_TRIGGER, settings.element_timeout_seconds):
        return LocationStatus.UNSUPPORTED, None
    if not _fill(
        driver,
        selectors.LOCATION_INPUT,
        context.requested_location,
        settings.element_timeout_seconds,
    ):
        return LocationStatus.UNSUPPORTED, None
    if not _click(driver, selectors.LOCATION_APPLY, settings.element_timeout_seconds):
        return LocationStatus.UNVERIFIED, None
    expected = context.geo_key.replace(" ", "")

    def location_was_applied(current: WebDriver) -> bool:
        for selector in selectors.LOCATION_DISPLAY:
            for element in current.find_elements(By.CSS_SELECTOR, selector):
                actual = (clean_text(element.text) or "").upper().replace(" ", "")
                if expected in actual:
                    return True
        return False

    try:
        WebDriverWait(
            driver,
            settings.element_timeout_seconds,
            ignored_exceptions=(StaleElementReferenceException,),
        ).until(location_was_applied)
    except TimeoutException:
        observed = _text(driver, selectors.LOCATION_DISPLAY, 1)
        return LocationStatus.UNVERIFIED, observed
    observed = _text(driver, selectors.LOCATION_DISPLAY, 1)
    return LocationStatus.VERIFIED, observed


class AmazonSeleniumScraper:
    """Reuse a browser throughout a job, retaining the marketplace profile across jobs."""

    def __init__(
        self,
        settings: Settings,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        challenge_notice: Callable[[bool], bool] | None = None,
    ) -> None:
        self.settings = settings
        self.sleep = sleep
        self.clock = clock
        self.challenge_notice = challenge_notice
        self._driver: WebDriver | None = None
        self._domain: str | None = None
        self._location: tuple[str, LocationStatus, str | None] | None = None
        self._last_navigation: float | None = None
        self._challenge_budget = float(settings.challenge_wait_seconds)
        self.navigation_heartbeat: Callable[[], bool] | None = None

    @contextmanager
    def session(self, domain: str) -> Iterator[WebDriver]:
        if self._driver is not None:
            if domain != self._domain:
                raise ValueError("Cannot change marketplace inside a browser session")
            yield self._driver
            return
        with chrome_session(self.settings, domain) as driver:
            self._driver, self._domain = driver, domain
            self._location = None
            self._challenge_budget = float(self.settings.challenge_wait_seconds)
            try:
                yield driver
            finally:
                self._driver, self._domain, self._location = None, None, None

    def _check_with_recovery(self, driver: WebDriver, domain: str) -> bool:
        try:
            _check_page_state(driver)
            return False
        except ScrapingError as exc:
            if exc.code != ScrapeErrorCode.BLOCKED:
                raise
        if self.settings.browser_headless or self._challenge_budget <= 0:
            raise ScrapingError(
                ScrapeErrorCode.BLOCKED,
                "Amazon requires a human browser check. Use the visible browser recovery setup; "
                "saved evidence is preserved.",
            )
        started = self.clock()
        try:
            while self.clock() - started < self._challenge_budget:
                if self.challenge_notice and not self.challenge_notice(True):
                    raise ScrapingError(ScrapeErrorCode.CANCELLED, "Job lease was lost")
                self.sleep(2)
                try:
                    _check_page_state(driver)
                    if _is_allowed_url(driver.current_url, domain):
                        return True
                except (StaleElementReferenceException, ScrapingError) as exc:
                    if isinstance(exc, ScrapingError) and exc.code != ScrapeErrorCode.BLOCKED:
                        raise
            raise ScrapingError(
                ScrapeErrorCode.BLOCKED,
                "The human browser check was not completed in time. Scraping is paused briefly; "
                "retry the job after the cooldown and complete the check in the visible browser.",
            )
        finally:
            self._challenge_budget = max(0.0, self._challenge_budget - (self.clock() - started))
            if self.challenge_notice:
                self.challenge_notice(False)

    def _navigate(self, driver: WebDriver, url: str, domain: str) -> None:
        if self.navigation_heartbeat and not self.navigation_heartbeat():
            raise ScrapingError(ScrapeErrorCode.CANCELLED, "Job lease was lost")
        if self._last_navigation is not None:
            delay = self.settings.min_navigation_interval_seconds - (
                self.clock() - self._last_navigation
            )
            if delay > 0:
                self.sleep(delay)
        driver.get(url)
        self._last_navigation = self.clock()
        resolved_challenge = self._check_with_recovery(driver, domain)
        if not _is_allowed_url(driver.current_url, domain):
            raise ScrapingError(
                ScrapeErrorCode.BLOCKED, "Amazon redirected outside the marketplace"
            )
        if resolved_challenge and urlparse(driver.current_url).path != urlparse(url).path:
            # A manual challenge may return to the homepage. Revisit the intended page once.
            self.sleep(self.settings.min_navigation_interval_seconds)
            driver.get(url)
            self._last_navigation = self.clock()
            self._check_with_recovery(driver, domain)

    def _prepare_location(
        self, driver: WebDriver, context: CollectionContext
    ) -> tuple[LocationStatus, str | None]:
        if self._location and self._location[0] == context.geo_key:
            return self._location[1], self._location[2]
        self._navigate(driver, marketplace_url(context.key.domain), context.key.domain)
        status, observed = _set_location(driver, context, self.settings)
        self._check_with_recovery(driver, context.key.domain)
        self._location = context.geo_key, status, observed
        return status, observed

    def scrape_product(self, context: CollectionContext) -> ScrapeOutcome:
        for attempt in range(2):
            try:
                return self._scrape_product_once(context)
            except StaleElementReferenceException:
                if attempt:
                    break
        return ScrapeOutcome(
            code=ScrapeErrorCode.BROWSER_ERROR,
            message="Amazon repeatedly changed the product page during extraction",
        )

    def _scrape_product_once(self, context: CollectionContext) -> ScrapeOutcome:
        try:
            with self.session(context.key.domain) as driver:
                location_status, observed_location = self._prepare_location(driver, context)
                self._navigate(
                    driver, product_url(context.key.domain, context.key.asin), context.key.domain
                )
                title = _text(driver, selectors.TITLE, self.settings.element_timeout_seconds)
                # A challenge can replace the DOM after an eager navigation returns.
                if not title and self._check_with_recovery(driver, context.key.domain):
                    self._navigate(
                        driver,
                        product_url(context.key.domain, context.key.asin),
                        context.key.domain,
                    )
                    title = _text(driver, selectors.TITLE, self.settings.element_timeout_seconds)
                if not title:
                    raise ScrapingError(ScrapeErrorCode.PARSE_ERROR, "Product title was not found")
                if context.requested_location:
                    observed_location = _text(driver, selectors.LOCATION_DISPLAY, 1)
                    location_status = (
                        LocationStatus.VERIFIED
                        if observed_location
                        and context.geo_key.replace(" ", "")
                        in observed_location.upper().replace(" ", "")
                        else LocationStatus.UNVERIFIED
                    )
                resolved_asin = product_asin_from_url(driver.current_url)
                if resolved_asin and resolved_asin != context.key.asin:
                    raise ScrapingError(
                        ScrapeErrorCode.VARIANT_MISMATCH, f"Amazon resolved to {resolved_asin}"
                    )
                price_text = _text(driver, selectors.PRICE, 2)
                price_amount, currency = parse_decimal_price(price_text, context.key.domain)
                image_url = _attribute(driver, selectors.IMAGE, "src")
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
                        message="Delivery location could not be verified for this marketplace",
                    )
                return ScrapeOutcome(snapshot=snapshot)
        except ScrapingError as exc:
            return ScrapeOutcome(code=exc.code, message=str(exc))
        except TimeoutException:
            return ScrapeOutcome(code=ScrapeErrorCode.TIMEOUT, message="Amazon page timed out")
        except StaleElementReferenceException:
            raise
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
            with self.session(context.key.domain) as driver:
                status, _ = self._prepare_location(driver, context)
                if context.requested_location and status != LocationStatus.VERIFIED:
                    return [], [
                        ItemFailure(
                            None,
                            ScrapeErrorCode.LOCATION_UNVERIFIED,
                            "Cannot verify delivery location",
                        )
                    ]
                for page in range(1, pages + 1):
                    self._navigate(
                        driver,
                        f"{marketplace_url(context.key.domain)}/s?k={quote_plus(query)}&page={page}",
                        context.key.domain,
                    )
                    cards = driver.find_elements(By.CSS_SELECTOR, selectors.SEARCH_CARD)
                    if not cards:
                        break
                    page_asins: set[str] = set()
                    for index in range(len(cards)):
                        candidate_data = None
                        for attempt in range(2):
                            try:
                                card = (
                                    cards[index]
                                    if not attempt
                                    else driver.find_elements(
                                        By.CSS_SELECTOR, selectors.SEARCH_CARD
                                    )[index]
                                )
                                asin = (card.get_attribute("data-asin") or "").strip().upper()
                                title = None
                                for selector in selectors.SEARCH_TITLE:
                                    found = card.find_elements(By.CSS_SELECTOR, selector)
                                    if found:
                                        title = clean_text(found[0].text)
                                        break
                                link = card.find_elements(By.CSS_SELECTOR, selectors.SEARCH_LINK)
                                url = link[0].get_attribute("href") if link else None
                                sponsored = "sponsored" in card.text.lower()
                                candidate_data = asin, title, url, sponsored
                                break
                            except (StaleElementReferenceException, IndexError):
                                continue
                        if candidate_data is None:
                            continue
                        asin, title, url, sponsored = candidate_data
                        if len(asin) != 10 or asin == context.key.asin or asin in seen:
                            continue
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
                    try:
                        next_disabled = bool(
                            next_buttons
                            and "disabled" in (next_buttons[0].get_attribute("class") or "")
                        )
                    except StaleElementReferenceException:
                        next_disabled = False
                    if page >= pages or not next_buttons or next_disabled:
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
