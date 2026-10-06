"""Integration tests for SQLAlchemy models, persistence, constraints, and relationships."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.models.entities import (
    CollectionJob,
    CompetitorRelationship,
    EvidenceArtifact,
    Product,
    ProductObservation,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_product_crud_and_unique_constraint(db_session: AsyncSession) -> None:
    # 1. Create product
    prod = Product(
        asin="B09XS7JWHH",
        domain="com",
        geo_key="__default__",
        title="Sony WH-1000XM5",
        brand="Sony",
    )
    db_session.add(prod)
    await db_session.flush()
    assert prod.id is not None
    assert prod.is_tracked is True

    # 2. Query product
    stmt = select(Product).where(Product.asin == "B09XS7JWHH", Product.domain == "com")
    res = await db_session.execute(stmt)
    fetched = res.scalar_one_or_none()
    assert fetched is not None
    assert fetched.title == "Sony WH-1000XM5"

    # 3. Duplicate constraint violation on (asin, domain, geo_key)
    dup = Product(
        asin="B09XS7JWHH",
        domain="com",
        geo_key="__default__",
        title="Duplicate",
    )
    db_session.add(dup)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_observation_provenance_and_evidence_relationship(db_session: AsyncSession) -> None:
    now = datetime.now(UTC)

    # 1. Product
    prod = Product(asin="B0CX23VSAS", domain="in", geo_key="273015")
    db_session.add(prod)
    await db_session.flush()

    # 2. Evidence Artifact
    evidence = EvidenceArtifact(
        evidence_type="html",
        storage_path="evidence/abcdef123456.html",
        content_size_bytes=104850,
        content_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        source_url="https://www.amazon.in/dp/B0CX23VSAS",
        collector="playwright_amazon",
        captured_at=now,
    )
    db_session.add(evidence)
    await db_session.flush()

    # 3. Product Observation with provenance
    obs = ProductObservation(
        product_id=prod.id,
        evidence_artifact_id=evidence.id,
        price_amount=Decimal("1299.00"),
        price_text="₹1,299",
        currency="INR",
        availability="In Stock",
        rating=4.3,
        rating_count=520,
        source_url="https://www.amazon.in/dp/B0CX23VSAS",
        captured_at=now,
        collector="playwright_amazon",
        extraction_method="json_ld_dom_hybrid",
        evidence_id=evidence.content_hash,
    )
    db_session.add(obs)
    await db_session.flush()

    # 4. Verify observation and relationship
    stmt = select(ProductObservation).where(ProductObservation.id == obs.id)
    result = await db_session.execute(stmt)
    loaded_obs = result.scalar_one()

    assert loaded_obs.price_amount == Decimal("1299.0000")
    assert loaded_obs.collector == "playwright_amazon"
    assert loaded_obs.extraction_method == "json_ld_dom_hybrid"
    assert loaded_obs.evidence_artifact is not None
    assert loaded_obs.evidence_artifact.content_hash == evidence.content_hash


@pytest.mark.asyncio
async def test_competitor_relationship_and_job_lifecycle(db_session: AsyncSession) -> None:
    # 1. Create baseline and competitor products
    base_prod = Product(asin="B01CCGW4OE", domain="com")
    comp_prod = Product(asin="B098FKXT8L", domain="com")
    db_session.add_all([base_prod, comp_prod])
    await db_session.flush()

    # 2. Create Job
    job = CollectionJob(
        kind="discover_competitors",
        product_id=base_prod.id,
        request_key=f"run-{uuid.uuid4()}",
        status="running",
        lease_token="worker-token-123",
        progress=50,
    )
    db_session.add(job)
    await db_session.flush()

    # 3. Create CompetitorRelationship
    rel = CompetitorRelationship(
        baseline_product_id=base_prod.id,
        competitor_product_id=comp_prod.id,
        match_score=0.85,
        match_method="deterministic",
        match_status="confirmed",
        search_rank=1,
        evidence_summary={"title_similarity": 0.88, "brand_match": True},
    )
    db_session.add(rel)
    await db_session.flush()

    assert rel.id is not None
    assert rel.match_score == 0.85
    assert rel.baseline_product.asin == "B01CCGW4OE"
    assert rel.competitor_product.asin == "B098FKXT8L"


@pytest.mark.asyncio
async def test_observation_deduplication_constraint(db_session: AsyncSession) -> None:
    """Processing the same product, capture time, collector and evidence twice is rejected."""

    now = datetime.now(UTC)
    prod = Product(asin="B0TESTDEDUP", domain="com")
    db_session.add(prod)
    await db_session.flush()

    evidence_hash = "a" * 64  # dummy SHA-256 length

    obs1 = ProductObservation(
        product_id=prod.id,
        source_url="https://www.amazon.com/dp/B0TESTDEDUP",
        captured_at=now,
        collector="playwright_amazon",
        extraction_method="structured_dom",
        evidence_id=evidence_hash,
    )
    db_session.add(obs1)
    await db_session.flush()

    obs2 = ProductObservation(
        product_id=prod.id,
        source_url="https://www.amazon.com/dp/B0TESTDEDUP",
        captured_at=now,
        collector="playwright_amazon",
        extraction_method="structured_dom",
        evidence_id=evidence_hash,  # Same hash → should be rejected
    )
    db_session.add(obs2)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_unchanged_html_at_a_later_time_is_a_new_observation(
    db_session: AsyncSession,
) -> None:
    prod = Product(asin="B0TESTDEDUP", domain="com")
    db_session.add(prod)
    await db_session.flush()
    now = datetime.now(UTC)
    for captured_at in (now, now + timedelta(days=1)):
        db_session.add(
            ProductObservation(
                product_id=prod.id,
                source_url="https://www.amazon.com/dp/B0TESTDEDUP",
                captured_at=captured_at,
                collector="playwright_amazon",
                extraction_method="structured_dom",
                evidence_id="a" * 64,
            )
        )
    await db_session.flush()
    rows = (await db_session.execute(select(ProductObservation))).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field", ["source_url", "captured_at", "collector", "extraction_method", "evidence_id"]
)
async def test_observation_requires_all_provenance(db_session: AsyncSession, field: str) -> None:
    prod = Product(asin="B0TESTPROV", domain="com")
    db_session.add(prod)
    await db_session.flush()
    values = {
        "product_id": prod.id,
        "source_url": "https://www.amazon.com/dp/B0TESTPROV",
        "captured_at": datetime.now(UTC),
        "collector": "playwright_amazon",
        "extraction_method": "structured_dom",
        "evidence_id": "b" * 64,
    }
    values.pop(field)
    db_session.add(ProductObservation(**values))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
