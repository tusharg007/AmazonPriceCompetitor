"""Append-only observation/evidence persistence. No historical updates or deletions."""

from dataclasses import asdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collector.base import EvidenceArtifactData
from app.models.entities import EvidenceArtifact, Product, ProductObservation
from app.models.schemas import ExtractedProduct


async def save_artifact(session: AsyncSession, evidence: EvidenceArtifactData) -> EvidenceArtifact:
    row = EvidenceArtifact(**asdict(evidence))
    session.add(row)
    await session.flush()
    return row


async def append_observation(
    session: AsyncSession,
    product: Product,
    extracted: ExtractedProduct,
    evidence: EvidenceArtifactData,
    job_id: UUID,
) -> ProductObservation:
    provenance = extracted.provenance
    existing = await session.scalar(
        select(ProductObservation).where(
            ProductObservation.product_id == product.id,
            ProductObservation.captured_at == provenance.timestamp,
            ProductObservation.collector == provenance.collector,
            ProductObservation.evidence_id == provenance.evidence_id,
        )
    )
    if existing is not None:
        return existing
    artifact = await save_artifact(session, evidence)
    values = extracted.model_dump(exclude={"asin", "domain", "title", "brand", "provenance"})
    values["raw_metadata"] = dict(values["raw_metadata"]) | {
        "_listing": {"title": extracted.title, "brand": extracted.brand}
    }
    row = ProductObservation(
        **values,
        product_id=product.id,
        job_id=job_id,
        evidence_artifact_id=artifact.id,
        source_url=provenance.source_url,
        captured_at=provenance.timestamp,
        collector=provenance.collector,
        extraction_method=provenance.extraction_method,
        evidence_id=provenance.evidence_id,
    )
    session.add(row)
    await session.flush()
    latest = await session.scalar(
        select(ProductObservation.id)
        .where(ProductObservation.product_id == product.id)
        .order_by(ProductObservation.captured_at.desc(), ProductObservation.id.desc())
        .limit(1)
    )
    if latest == row.id:
        product.title, product.brand = extracted.title, extracted.brand
    return row
