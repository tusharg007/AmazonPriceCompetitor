"""Persist analysis and claim links in one fenced transaction."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.claims import PROMPT_VERSION, SCHEMA_VERSION
from app.models.entities import (
    AnalysisClaim,
    AnalysisRun,
    ClaimEvidence,
    Product,
    ProductObservation,
    utc_now,
)


async def find_run(
    session: AsyncSession, product_id: int, input_hash: str, model: str
) -> AnalysisRun | None:
    return await session.scalar(
        select(AnalysisRun).where(
            AnalysisRun.product_id == product_id,
            AnalysisRun.input_hash == input_hash,
            AnalysisRun.model == model,
            AnalysisRun.prompt_version == PROMPT_VERSION,
            AnalysisRun.schema_version == SCHEMA_VERSION,
        )
    )


async def save_run(
    session: AsyncSession,
    product_id: int,
    job_id: UUID | None,
    input_hash: str,
    model: str,
    evidence: dict[str, Any],
    output: dict[str, Any] | None,
    claims: list[dict[str, Any]],
    error: str | None = None,
) -> AnalysisRun:
    run = await find_run(session, product_id, input_hash, model)
    if run and run.status == "succeeded":
        return run
    if run is None:
        run = AnalysisRun(
            product_id=product_id,
            input_hash=input_hash,
            model=model,
            prompt_version=PROMPT_VERSION,
            schema_version=SCHEMA_VERSION,
            input_evidence=evidence,
        )
        session.add(run)
    run.job_id, run.status, run.raw_output, run.error_message, run.completed_at = (
        job_id,
        "failed" if error else "succeeded",
        output,
        error,
        utc_now(),
    )
    await session.flush()
    for item in claims:
        claim = AnalysisClaim(
            run_id=run.id,
            claim_type=item["claim_type"],
            claim_text=item["claim_text"],
            claim_value=item["claim_value"],
        )
        session.add(claim)
        await session.flush()
        for source in item["sources"]:
            session.add(
                ClaimEvidence(
                    claim_id=claim.id,
                    observation_id=UUID(source["observation_id"]),
                    role=source["role"],
                )
            )
    await session.flush()
    return run


async def claims_with_sources(
    session: AsyncSession, run_id: UUID
) -> tuple[list[AnalysisClaim], list[Any]]:
    claims = list(
        await session.scalars(
            select(AnalysisClaim)
            .where(AnalysisClaim.run_id == run_id)
            .order_by(AnalysisClaim.created_at, AnalysisClaim.id)
        )
    )
    sources = list(
        (
            await session.execute(
                select(ClaimEvidence, ProductObservation, Product)
                .join(ProductObservation, ProductObservation.id == ClaimEvidence.observation_id)
                .join(Product, Product.id == ProductObservation.product_id)
                .where(ClaimEvidence.claim_id.in_([c.id for c in claims]))
            )
        ).all()
    )
    return claims, sources
