"""SQLAlchemy 2.0 entities for products, observations, provenance, and relationships."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(UTC)


class Product(Base):
    """Core tracked Amazon product entity identified by ASIN, marketplace domain, and geographic location."""

    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("asin", "domain", "geo_key", name="uq_product_identity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asin: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    geo_key: Mapped[str] = mapped_column(
        String(50), nullable=False, default="__default__", index=True
    )
    requested_location: Mapped[str | None] = mapped_column(String(50), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_tracked: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    # Relationships
    observations: Mapped[list[ProductObservation]] = relationship(
        "ProductObservation",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="desc(ProductObservation.captured_at)",
    )
    jobs: Mapped[list[CollectionJob]] = relationship(
        "CollectionJob",
        back_populates="product",
        cascade="all, delete-orphan",
    )
    competitor_relationships: Mapped[list[CompetitorRelationship]] = relationship(
        "CompetitorRelationship",
        foreign_keys="CompetitorRelationship.baseline_product_id",
        back_populates="baseline_product",
        cascade="all, delete-orphan",
    )


class EvidenceArtifact(Base):
    """Immutable evidence artifact capturing raw HTML, screenshot, or microdata payloads."""

    __tablename__ = "evidence_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    evidence_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # html, screenshot, jsonld, metadata
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # SHA-256
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    collector: Mapped[str] = mapped_column(String(100), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    # Relationships
    observations: Mapped[list[ProductObservation]] = relationship(
        "ProductObservation",
        back_populates="evidence_artifact",
    )


class ProductObservation(Base):
    """Append-only historical observation of a product listing with strict provenance."""

    __tablename__ = "product_observations"
    __table_args__ = (
        # Reprocessing the same capture is a duplicate; a later capture of identical HTML is not.
        UniqueConstraint(
            "product_id",
            "captured_at",
            "collector",
            "evidence_id",
            name="uq_observation_evidence",
        ),
        CheckConstraint(
            "length(source_url) > 0 AND length(collector) > 0 "
            "AND length(extraction_method) > 0 AND length(evidence_id) > 0",
            name="ck_observation_provenance",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collection_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    evidence_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("evidence_artifacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Extracted observation data
    price_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    price_text: Mapped[str | None] = mapped_column(String(100), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    availability: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    rating_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    location_status: Mapped[str] = mapped_column(String(50), default="default", nullable=False)
    observed_location: Mapped[str | None] = mapped_column(String(100), nullable=True)
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    variant: Mapped[str | None] = mapped_column(String(255), nullable=True)
    condition: Mapped[str | None] = mapped_column(String(100), nullable=True)
    categories: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    images: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    raw_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # Required provenance metadata
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    collector: Mapped[str] = mapped_column(String(100), nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(100), nullable=False)
    evidence_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    # Relationships
    product: Mapped[Product] = relationship("Product", back_populates="observations")
    job: Mapped[CollectionJob | None] = relationship("CollectionJob", back_populates="observations")
    evidence_artifact: Mapped[EvidenceArtifact | None] = relationship(
        "EvidenceArtifact", back_populates="observations"
    )


class CompetitorRelationship(Base):
    """Pairwise competitor relationship linking a baseline product to a discovered competitor."""

    __tablename__ = "competitor_relationships"
    __table_args__ = (
        UniqueConstraint("baseline_product_id", "competitor_product_id", name="uq_competitor_pair"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    baseline_product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    competitor_product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    match_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    match_method: Mapped[str] = mapped_column(String(50), nullable=False, default="deterministic")
    match_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending", index=True
    )
    exclusion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sponsored: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    search_query: Mapped[str | None] = mapped_column(String(255), nullable=True)
    evidence_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    # Relationships
    baseline_product: Mapped[Product] = relationship(
        "Product", foreign_keys=[baseline_product_id], back_populates="competitor_relationships"
    )
    competitor_product: Mapped[Product] = relationship(
        "Product", foreign_keys=[competitor_product_id]
    )


class MatchEvidence(Base):
    """Append-only record of the exact observations and inputs used by a decision."""

    __tablename__ = "match_evidence"
    __table_args__ = (
        UniqueConstraint(
            "match_id",
            "baseline_observation_id",
            "candidate_observation_id",
            "policy_version",
            name="uq_match_capture_policy",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    match_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("competitor_relationships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    baseline_observation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("product_observations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    candidate_observation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("product_observations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("collection_jobs.id", ondelete="SET NULL")
    )
    evidence_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="attribute_comparison"
    )
    policy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    evidence_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class CollectionJob(Base):
    """Collection job tracking async scraping task execution, lease state, and diagnostics."""

    __tablename__ = "collection_jobs"
    __table_args__ = (
        Index(
            "idx_jobs_active_dedup",
            "kind",
            "product_id",
            "request_key",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
            sqlite_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    kind: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # scrape_product, discover_competitors
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="queued", index=True)
    request_key: Mapped[str] = mapped_column(String(100), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    lease_token: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    product: Mapped[Product] = relationship("Product", back_populates="jobs")
    observations: Mapped[list[ProductObservation]] = relationship(
        "ProductObservation", back_populates="job"
    )
