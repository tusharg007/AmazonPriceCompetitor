from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from src.config import get_settings
from src.models import ScrapeErrorCode
from src.scraping.amazon import AmazonSeleniumScraper, _check_page_state
from src.scraping.browser import chrome_session, profile_lock
from src.scraping.errors import ScrapingError


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class ChallengePage:
    def __init__(self, clock: FakeClock, clears_at: float | None) -> None:
        self.clock, self.clears_at = clock, clears_at
        self.current_url = "https://www.amazon.in/"
        self.visits: list[float] = []
        self.title = "Amazon"
        self.page_source = "hidden script text: enter the characters you see"

    def find_elements(self, _by: Any, selector: str) -> list[Mock]:
        if selector == "#captchacharacters":
            visible = self.clears_at is None or self.clock() < self.clears_at
            return [Mock(is_displayed=Mock(return_value=visible))]
        return []

    def get(self, url: str) -> None:
        self.visits.append(self.clock())
        self.current_url = url


def test_hidden_challenge_markup_does_not_block_product() -> None:
    page = ChallengePage(FakeClock(), clears_at=0)
    _check_page_state(page)  # type: ignore[arg-type]


def test_manual_challenge_recovery_preserves_session_and_reports_wait() -> None:
    clock = FakeClock()
    page = ChallengePage(clock, clears_at=2)
    notices: list[bool] = []

    def notice(waiting: bool) -> bool:
        notices.append(waiting)
        return True

    scraper = AmazonSeleniumScraper(
        replace(get_settings(), browser_headless=False, challenge_wait_seconds=6),
        sleep=clock.sleep,
        clock=clock,
        challenge_notice=notice,
    )
    assert scraper._check_with_recovery(page, "in")  # type: ignore[arg-type]
    assert notices == [True, False]
    assert page.visits == []  # Recovery waits for the human; it never submits the challenge.
    assert scraper._challenge_budget == 4


def test_unresolved_challenge_has_bounded_wait_and_stops_navigation() -> None:
    clock = FakeClock()
    page = ChallengePage(clock, clears_at=None)
    scraper = AmazonSeleniumScraper(
        replace(get_settings(), browser_headless=False, challenge_wait_seconds=6),
        sleep=clock.sleep,
        clock=clock,
    )
    with pytest.raises(ScrapingError) as caught:
        scraper._navigate(page, "https://www.amazon.in/dp/B0H3TV3MLG", "in")  # type: ignore[arg-type]
    assert caught.value.code == ScrapeErrorCode.BLOCKED
    assert clock.now == 6
    assert len(page.visits) == 1


def test_navigation_is_paced_before_each_request() -> None:
    clock = FakeClock()
    page = ChallengePage(clock, clears_at=0)
    scraper = AmazonSeleniumScraper(
        replace(get_settings(), min_navigation_interval_seconds=5),
        sleep=clock.sleep,
        clock=clock,
    )
    scraper._navigate(page, "https://www.amazon.in/", "in")  # type: ignore[arg-type]
    scraper._navigate(page, "https://www.amazon.in/dp/B0H3TV3MLG", "in")  # type: ignore[arg-type]
    assert page.visits == [0, 5]


def test_job_session_is_reused_and_closed_once(monkeypatch: pytest.MonkeyPatch) -> None:
    driver = Mock()
    events: list[str] = []

    @contextmanager
    def fake_session(*_: Any) -> Any:
        events.append("open")
        try:
            yield driver
        finally:
            events.append("close")

    monkeypatch.setattr("src.scraping.amazon.chrome_session", fake_session)
    scraper = AmazonSeleniumScraper(get_settings())
    with scraper.session("in") as first:
        with scraper.session("in") as second:
            assert first is second
        assert events == ["open"]
    assert events == ["open", "close"]
    assert scraper._driver is None


def test_persistent_browser_profile_survives_normal_shutdown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    driver = Mock()
    monkeypatch.setattr("src.scraping.browser.webdriver.Chrome", Mock(return_value=driver))
    settings = replace(get_settings(), browser_profile_dir=tmp_path, selenium_url=None)
    with chrome_session(settings, "in"):
        (tmp_path / "in" / "Cookies").write_text("session-cookie")
    assert (tmp_path / "in" / "Cookies").read_text() == "session-cookie"
    driver.quit.assert_called_once()
    with (
        profile_lock(tmp_path / "in"),
        pytest.raises(RuntimeError, match="already in use"),
        profile_lock(tmp_path / "in"),
    ):
        pass
    with profile_lock(tmp_path / "in"):
        pass  # The OS lock is released, including after a worker exits unexpectedly.
