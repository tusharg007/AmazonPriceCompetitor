"""Stable collection error codes carried forward from V1."""

from enum import StrEnum


class ScrapeErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"
    LOCATION_UNVERIFIED = "location_unverified"
    VARIANT_MISMATCH = "variant_mismatch"
    BLOCKED = "blocked"
    TIMEOUT = "timeout"
    PARSE_ERROR = "parse_error"
    BROWSER_ERROR = "browser_error"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    CANCELLED = "cancelled"
