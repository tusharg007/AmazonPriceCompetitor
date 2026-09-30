"""Immutable data contracts shared by persistence, scraping, services, and UI."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from src.config import SUPPORTED_DOMAINS

ASIN_PATTERN = re.compile(r"^[A-Z0-9]{10}$")
DEFAULT_GEO_KEY = "__default__"


class ValidationError(ValueError):
    """Raised for invalid public application inputs."""


class LocationStatus(StrEnum):
    DEFAULT = "default"
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    UNSUPPORTED = "unsupported"


class JobKind(StrEnum):
    SCRAPE_PRODUCT = "scrape_product"
    DISCOVER_COMPETITORS = "discover_competitors"
    ANALYZE = "analyze"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


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


def normalize_asin(asin: str) -> str:
    normalized = asin.strip().upper()
    if not ASIN_PATTERN.fullmatch(normalized):
        raise ValidationError("ASIN must contain exactly 10 uppercase letters or digits")
    return normalized


def normalize_domain(domain: str) -> str:
    normalized = domain.strip().lower().removeprefix("amazon.")
    if normalized not in SUPPORTED_DOMAINS:
        raise ValidationError(f"Domain must be one of: {', '.join(SUPPORTED_DOMAINS)}")
    return normalized


def normalize_geo(location: str | None) -> tuple[str, str | None]:
    requested = (location or "").strip()
    if not requested:
        return DEFAULT_GEO_KEY, None
    if len(requested) > 32:
        raise ValidationError("Postal/delivery location must be 32 characters or fewer")
    return re.sub(r"\s+", " ", requested).upper(), requested


@dataclass(frozen=True, slots=True)
class ProductKey:
    asin: str
    domain: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "asin", normalize_asin(self.asin))
        object.__setattr__(self, "domain", normalize_domain(self.domain))


@dataclass(frozen=True, slots=True)
class CollectionContext:
    id: int
    key: ProductKey
    geo_key: str
    requested_location: str | None
    is_tracked: bool
    latest_snapshot_id: int | None = None
    active_complete_run_id: int | None = None


@dataclass(frozen=True, slots=True)
class ProductSnapshot:
    context_id: int
    requested_asin: str
    resolved_asin: str | None
    title: str | None
    canonical_url: str | None
    captured_at: datetime
    capture_key: str
    domain: str
    requested_location: str | None
    observed_location: str | None = None
    location_status: LocationStatus = LocationStatus.DEFAULT
    brand: str | None = None
    price_amount: Decimal | None = None
    price_text: str | None = None
    currency: str | None = None
    price_kind: str | None = None
    availability: str | None = None
    rating: float | None = None
    rating_count: int | None = None
    images: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    category_path: tuple[str, ...] = ()
    product_overview: tuple[str, ...] = ()
    variant: str | None = None
    condition: str | None = None
    source: str = "selenium"
    extractor_version: str = "1"
    legacy_payload: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class SearchCandidate:
    asin: str
    title: str | None
    rank: int
    query: str
    sponsored: bool = False
    canonical_url: str | None = None
    category: str | None = None


@dataclass(frozen=True, slots=True)
class ItemFailure:
    asin: str | None
    code: ScrapeErrorCode
    message: str


@dataclass(frozen=True, slots=True)
class ScrapeOutcome:
    snapshot: ProductSnapshot | None = None
    code: ScrapeErrorCode | None = None
    message: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.snapshot is not None and self.code is None


@dataclass(frozen=True, slots=True)
class CompetitorRunResult:
    run_id: int | None
    status: JobStatus
    stored_context_ids: tuple[int, ...] = ()
    failures: tuple[ItemFailure, ...] = ()


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    kind: JobKind
    context_id: int
    request_key: str
    status: JobStatus
    options: dict[str, Any] = field(default_factory=dict)
    attempts: int = 0
    lease_token: str | None = None
    progress: int = 0
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class CompetitorInsight:
    asin: str
    key_points: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AnalysisOutput:
    summary: str
    positioning: str
    top_competitors: tuple[CompetitorInsight, ...]
    recommendations: tuple[str, ...]
