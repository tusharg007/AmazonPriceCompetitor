"""Evaluate captured candidate observations inside the collection's owned transaction."""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.matching.scoring import evaluate_match
from app.models.entities import Product, ProductObservation
from app.repository.matching import save_decision
from app.services.records import observation_record


async def match_candidate(
    session: AsyncSession,
    baseline_id: UUID,
    candidate: ProductObservation,
    job_id: UUID,
    discovery: dict[str, Any],
) -> None:
    baseline = await session.get(ProductObservation, baseline_id)
    if baseline is None:
        raise ValueError("Matching baseline observation is missing")
    baseline_product = await session.get(Product, baseline.product_id)
    candidate_product = await session.get(Product, candidate.product_id)
    assert baseline_product is not None and candidate_product is not None
    a, b = (
        observation_record(baseline_product, baseline),
        observation_record(candidate_product, candidate),
    )
    b["sponsored"] = discovery.get("sponsored", False)
    decision = evaluate_match(a, b)
    evidence = dict(decision.evidence)
    evidence["sources"] = [
        {
            key: record[key]
            for key in (
                "observation_id",
                "source_url",
                "captured_at",
                "collector",
                "extraction_method",
                "evidence_id",
                "evidence_artifact_id",
            )
        }
        for record in (a, b)
    ]
    evidence["search_evidence_artifact_id"] = discovery.get("search_evidence_artifact_id")
    await save_decision(
        session,
        baseline.product_id,
        candidate.product_id,
        baseline.id,
        candidate.id,
        job_id,
        type(decision)(decision.score, decision.status, decision.reason, evidence),
        discovery,
    )
