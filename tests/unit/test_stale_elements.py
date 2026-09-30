from typing import Any

from selenium.common.exceptions import StaleElementReferenceException

from src.config import get_settings
from src.models import CollectionContext, ProductKey, ScrapeErrorCode, ScrapeOutcome
from src.scraping.amazon import AmazonSeleniumScraper, _attribute, _click, _fill, _text


class ChangingElement:
    def __init__(self, text: str = "Product title", *, stale: bool = False) -> None:
        self.value = text
        self.stale = stale

    @property
    def text(self) -> str:
        if self.stale:
            raise StaleElementReferenceException("element was replaced")
        return self.value

    def click(self) -> None:
        if self.stale:
            raise StaleElementReferenceException("element was replaced")

    def get_attribute(self, _name: str) -> str:
        if self.stale:
            raise StaleElementReferenceException("element was replaced")
        return "https://example.test/image.jpg"

    def clear(self) -> None:
        if self.stale:
            raise StaleElementReferenceException("element was replaced")

    def send_keys(self, _value: str) -> None:
        if self.stale:
            raise StaleElementReferenceException("element was replaced")


class ChangingDriver:
    def __init__(self) -> None:
        self.lookups = 0

    def find_element(self, *_args: Any) -> ChangingElement:
        self.lookups += 1
        return ChangingElement(stale=self.lookups == 1)


def test_text_and_click_relocate_stale_elements() -> None:
    text_driver = ChangingDriver()
    assert _text(text_driver, ("#title",), 2) == "Product title"  # type: ignore[arg-type]
    assert text_driver.lookups == 2

    click_driver = ChangingDriver()
    assert _click(click_driver, ("#location",), 2)  # type: ignore[arg-type]
    assert click_driver.lookups == 2

    image_driver = ChangingDriver()
    assert (
        _attribute(image_driver, ("#image",), "src", 2)  # type: ignore[arg-type]
        == "https://example.test/image.jpg"
    )
    assert image_driver.lookups == 2

    input_driver = ChangingDriver()
    assert _fill(input_driver, ("#postal-code",), "273015", 2)  # type: ignore[arg-type]
    assert input_driver.lookups == 2


def test_product_scrape_retries_once_with_new_session(monkeypatch: Any) -> None:
    scraper = AmazonSeleniumScraper(get_settings())
    context = CollectionContext(1, ProductKey("B0H3TV3MLG", "in"), "273015", "273015", True)
    attempts = 0

    def scrape_once(_context: CollectionContext) -> ScrapeOutcome:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise StaleElementReferenceException("page changed")
        return ScrapeOutcome()

    monkeypatch.setattr(scraper, "_scrape_product_once", scrape_once)
    assert scraper.scrape_product(context) == ScrapeOutcome()
    assert attempts == 2

    def always_stale(_context: CollectionContext) -> ScrapeOutcome:
        raise StaleElementReferenceException("page changed")

    monkeypatch.setattr(scraper, "_scrape_product_once", always_stale)
    failed = scraper.scrape_product(context)
    assert failed.code == ScrapeErrorCode.BROWSER_ERROR
    assert failed.message == "Amazon repeatedly changed the product page during extraction"
