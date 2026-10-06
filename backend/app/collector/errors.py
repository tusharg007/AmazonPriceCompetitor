"""V1 collection error contract plus compatible existing collector exceptions."""

from app.models.enums import ScrapeErrorCode


class ScrapingError(RuntimeError):
    def __init__(self, code: ScrapeErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


TRANSIENT_CODES = {ScrapeErrorCode.TIMEOUT, ScrapeErrorCode.BROWSER_ERROR}


class ScrapingBlockedError(ScrapingError):
    def __init__(self, message: str) -> None:
        super().__init__(ScrapeErrorCode.BLOCKED, message)


class PageNotFoundError(ScrapingError):
    def __init__(self, message: str) -> None:
        super().__init__(ScrapeErrorCode.NOT_FOUND, message)
