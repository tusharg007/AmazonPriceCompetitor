"""Unit tests for Pydantic domain models and validation."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.models.schemas import (
    ExtractedProduct,
    ProductCreate,
    ProvenanceMetadata,
)


def test_provenance_metadata_immutability() -> None:
    now = datetime.now(UTC)
    prov = ProvenanceMetadata(
        source_url="https://www.amazon.com/dp/B09XS7JWHH",
        timestamp=now,
        collector="playwright_amazon",
        extraction_method="json_ld",
        evidence_id="a1b2c3d4e5f6",
    )
    assert prov.source_url == "https://www.amazon.com/dp/B09XS7JWHH"
    assert prov.collector == "playwright_amazon"
    assert prov.evidence_id == "a1b2c3d4e5f6"

    # Frozen model should reject modifications
    with pytest.raises((TypeError, ValueError)):
        prov.collector = "tampered"  # type: ignore[misc]


def test_extracted_product_validation() -> None:
    now = datetime.now(UTC)
    prov = ProvenanceMetadata(
        source_url="https://www.amazon.com/dp/B09XS7JWHH",
        timestamp=now,
        collector="playwright_amazon",
        extraction_method="json_ld",
        evidence_id="hash123",
    )

    product = ExtractedProduct(
        asin="B09XS7JWHH",
        domain="com",
        title="Sony Headphones",
        brand="Sony",
        price_amount=Decimal("398.00"),
        price_text="$398.00",
        currency="USD",
        rating=4.6,
        rating_count=12000,
        provenance=prov,
    )
    assert product.asin == "B09XS7JWHH"
    assert product.domain == "com"
    assert product.price_amount == Decimal("398.00")
    assert product.provenance.extraction_method == "json_ld"


def test_extracted_product_invalid_asin() -> None:
    now = datetime.now(UTC)
    prov = ProvenanceMetadata(
        source_url="https://www.amazon.com/dp/invalid",
        timestamp=now,
        collector="test",
        extraction_method="dom",
        evidence_id="hash",
    )

    # Short ASIN
    with pytest.raises(ValueError):
        ExtractedProduct(
            asin="SHORT",
            domain="com",
            provenance=prov,
        )

    # Non-alphanumeric
    with pytest.raises(ValueError, match="10 alphanumeric"):
        ExtractedProduct(
            asin="B09-S7JWHH",
            domain="com",
            provenance=prov,
        )


def test_product_create_schema() -> None:
    item = ProductCreate(asin="b0cx23vsas", domain="amazon.in", requested_location="273015")
    assert item.asin == "B0CX23VSAS"
    assert item.domain == "in"
    assert item.requested_location == "273015"

    with pytest.raises(ValueError, match="Unsupported domain"):
        ProductCreate(asin="B0CX23VSAS", domain="xyz")
