"""Scraping errors with stable, user-safe codes."""

from __future__ import annotations

from src.models import ScrapeErrorCode


class ScrapingError(RuntimeError):
    def __init__(self, code: ScrapeErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


TRANSIENT_CODES = {ScrapeErrorCode.TIMEOUT, ScrapeErrorCode.BROWSER_ERROR}
