"""Pydantic schemas for data validation, extraction models, and API responses."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.validation import (
    ASIN_REGEX,
    SUPPORTED_DOMAINS,
    amazon_identity,
    normalize_asin,
    normalize_domain,
    normalize_location,
)


class ProvenanceMetadata(BaseModel):
    """Guaranteed provenance metadata for every extracted observation."""

    source_url: str = Field(
        ..., min_length=1, description="Fully-qualified URL where the observation was obtained."
    )
    timestamp: datetime = Field(..., description="UTC timestamp when data was fetched.")
    collector: str = Field(
        ..., min_length=1, description="Name or identifier of the collector engine."
    )
    extraction_method: str = Field(
        ...,
        min_length=1,
        description="Extraction methodology: 'json_ld', 'structured_dom', or 'hybrid'.",
    )
    evidence_id: str = Field(
        ...,
        min_length=1,
        description="Identifier (SHA-256 hash or UUID) referencing the raw stored evidence.",
    )

    model_config = ConfigDict(frozen=True)


class ExtractedProduct(BaseModel):
    """Normalized structured product listing extracted from Amazon DOM or JSON-LD."""

    asin: str = Field(..., min_length=10, max_length=10)
    domain: str = Field(..., description="Amazon marketplace domain, e.g. 'com', 'in'.")
    title: str | None = None
    brand: str | None = None
    price_amount: Decimal | None = None
    price_text: str | None = None
    currency: str | None = None
    availability: str | None = None
    rating: float | None = Field(default=None, ge=0.0, le=5.0)
    rating_count: int | None = Field(default=None, ge=0)
    price_kind: str | None = None
    location_status: str = "default"
    observed_location: str | None = None
    canonical_url: str | None = None
    variant: str | None = None
    condition: str | None = None
    categories: list[str] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: ProvenanceMetadata

    @field_validator("asin")
    @classmethod
    def validate_asin(cls, v: str) -> str:
        cleaned = v.strip().upper()
        if not ASIN_REGEX.match(cleaned):
            raise ValueError(f"Invalid ASIN '{v}'. Must be 10 alphanumeric characters.")
        return cleaned

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, v: str) -> str:
        cleaned = v.strip().lower().removeprefix("amazon.")
        if cleaned not in SUPPORTED_DOMAINS:
            raise ValueError(f"Unsupported domain '{v}'. Supported: {SUPPORTED_DOMAINS}")
        return cleaned


class ExtractedSearchCandidate(BaseModel):
    """Discovered competitor search result item."""

    asin: str = Field(..., min_length=10, max_length=10)
    title: str
    price_amount: Decimal | None = None
    price_text: str | None = None
    currency: str | None = None
    rating: float | None = None
    rating_count: int | None = None
    rank: int = Field(..., ge=1)
    sponsored: bool = False
    detail_url: str
    image_url: str | None = None
    provenance: ProvenanceMetadata


class ProductCreate(BaseModel):
    """Payload to register a product for tracking."""

    asin: str = Field(default="", description="ASIN, or omit when supplying an Amazon product URL")
    domain: str = "com"
    requested_location: str | None = None
    url: str | None = Field(default=None, max_length=2048)

    model_config = ConfigDict(
        extra="forbid",
        validate_default=True,
        json_schema_extra={"anyOf": [{"required": ["asin"]}, {"required": ["url"]}]},
    )

    @model_validator(mode="before")
    @classmethod
    def resolve_url(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("url") is not None:
            data = dict(data)
            if not isinstance(data["url"], str):
                raise ValueError("URL must be a string")
            asin, domain = amazon_identity(data["url"])
            if "asin" in data and (
                not isinstance(data["asin"], str) or normalize_asin(data["asin"]) != asin
            ):
                raise ValueError("ASIN disagrees with URL")
            if "domain" in data and (
                not isinstance(data["domain"], str) or normalize_domain(data["domain"]) != domain
            ):
                raise ValueError("Domain disagrees with URL")
            data.update(asin=asin, domain=domain)
        return data

    @field_validator("asin")
    @classmethod
    def validate_asin(cls, v: str) -> str:
        return normalize_asin(v)

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, v: str) -> str:
        return normalize_domain(v)

    @model_validator(mode="after")
    def delivery_context(self) -> Self:
        _, self.requested_location = normalize_location(self.domain, self.requested_location)
        return self


class APIResponse(BaseModel):
    @field_validator("*", mode="after")
    @classmethod
    def explicit_utc(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return value


class ProductRead(APIResponse):
    """Product response model."""

    id: int
    asin: str
    domain: str
    geo_key: str
    requested_location: str | None
    title: str | None
    brand: str | None
    is_tracked: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EvidenceArtifactRead(APIResponse):
    """Evidence artifact summary response."""

    id: uuid.UUID
    evidence_type: str
    storage_path: str
    content_size_bytes: int
    content_hash: str
    source_url: str
    collector: str
    captured_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductObservationRead(APIResponse):
    """Observation item response."""

    id: uuid.UUID
    product_id: int
    job_id: uuid.UUID | None
    evidence_artifact_id: uuid.UUID | None
    price_amount: Decimal | None
    price_text: str | None
    currency: str | None
    availability: str | None
    rating: float | None
    rating_count: int | None
    location_status: str = "default"
    source_url: str
    captured_at: datetime
    collector: str
    extraction_method: str
    evidence_id: str

    model_config = ConfigDict(from_attributes=True)


class CollectionJobRead(APIResponse):
    """Job status response."""

    id: uuid.UUID
    kind: str
    product_id: int
    status: str
    progress: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result: dict[str, Any]
    attempts: int
    max_attempts: int

    model_config = ConfigDict(from_attributes=True)


class ProductResponse(ProductRead):
    latest_observation: ProductObservationRead | None
    competitor_count: int
    last_collected_at: datetime | None


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    limit: int


JobStatus = Literal["queued", "running", "succeeded", "partial", "failed", "cancelled"]
MatchStatus = Literal["pending", "confirmed", "ambiguous", "rejected"]


class CollectRequest(BaseModel):
    include_competitors: bool = Field(default=False, strict=True)
    model_config = ConfigDict(extra="forbid")


class JobProgress(BaseModel):
    status: str
    progress: int
    error_code: str | None
    error_message: str | None
    model_config = ConfigDict(from_attributes=True)


class CompetitorRead(BaseModel):
    id: uuid.UUID
    baseline_product_id: int
    competitor_product_id: int
    match_score: float
    match_method: str
    match_status: str
    exclusion_reason: str | None
    search_rank: int | None
    sponsored: bool
    search_query: str | None
    evidence_summary: dict[str, Any]
    competitor: ProductResponse | None = None
    model_config = ConfigDict(from_attributes=True)


class ValidationIssue(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class ErrorResponse(BaseModel):
    error: str
    detail: str
    issues: list[ValidationIssue] | None = None


class HealthCheckResponse(BaseModel):
    """Health check endpoint response model."""

    status: str
    app_name: str
    app_version: str
    database: dict[str, Any]
    browser_environment: dict[str, Any]
    timestamp: datetime
