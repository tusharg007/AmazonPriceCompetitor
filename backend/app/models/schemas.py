"""Pydantic schemas for data validation, extraction models, and API responses."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

ASIN_REGEX = re.compile(r"^[A-Z0-9]{10}$")
SUPPORTED_DOMAINS = ("com", "in", "ca", "co.uk", "de", "fr", "it", "ae")


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

    asin: str
    domain: str = "com"
    requested_location: str | None = None

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
            raise ValueError(f"Unsupported domain '{v}'.")
        return cleaned


class ProductRead(BaseModel):
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


class EvidenceArtifactRead(BaseModel):
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


class ProductObservationRead(BaseModel):
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
    source_url: str
    captured_at: datetime
    collector: str
    extraction_method: str
    evidence_id: str

    model_config = ConfigDict(from_attributes=True)


class CollectionJobRead(BaseModel):
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

    model_config = ConfigDict(from_attributes=True)


class HealthCheckResponse(BaseModel):
    """Health check endpoint response model."""

    status: str
    app_name: str
    app_version: str
    database: dict[str, Any]
    browser_environment: dict[str, Any]
    timestamp: datetime
