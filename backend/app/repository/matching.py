"""Atomic relationship upserts and idempotent, append-only decision evidence."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.matching.scoring import POLICY_VERSION, MatchDecision
from app.models.entities import CompetitorRelationship, MatchEvidence, utc_now


async def save_decision(
    session: AsyncSession,
    baseline_id: int,
    candidate_id: int,
    baseline_observation_id: UUID,
    candidate_observation_id: UUID,
    job_id: UUID,
    decision: MatchDecision,
    discovery: dict[str, Any],
) -> None:
    processed = await session.scalar(
        select(MatchEvidence.id)
        .join(CompetitorRelationship, CompetitorRelationship.id == MatchEvidence.match_id)
        .where(
            CompetitorRelationship.baseline_product_id == baseline_id,
            CompetitorRelationship.competitor_product_id == candidate_id,
            MatchEvidence.baseline_observation_id == baseline_observation_id,
            MatchEvidence.candidate_observation_id == candidate_observation_id,
            MatchEvidence.policy_version == POLICY_VERSION,
        )
    )
    if processed is not None:
        return
    insert = pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    summary = dict(decision.evidence) | {
        "baseline_observation_id": str(baseline_observation_id),
        "candidate_observation_id": str(candidate_observation_id),
        "discovery_job_id": str(job_id),
    }
    values = {
        "match_score": decision.score,
        "match_method": "deterministic",
        "match_status": decision.status,
        "exclusion_reason": decision.reason,
        "search_rank": discovery.get("rank"),
        "sponsored": discovery.get("sponsored", False),
        "search_query": discovery.get("search_query", "")[:255],
        "evidence_summary": summary,
        "updated_at": utc_now(),
    }
    identity = await session.scalar(
        insert(CompetitorRelationship)
        .values(baseline_product_id=baseline_id, competitor_product_id=candidate_id, **values)
        .on_conflict_do_update(
            index_elements=["baseline_product_id", "competitor_product_id"], set_=values
        )
        .returning(CompetitorRelationship.id)
    )
    assert identity is not None
    await session.execute(
        insert(MatchEvidence)
        .values(
            match_id=identity,
            baseline_observation_id=baseline_observation_id,
            candidate_observation_id=candidate_observation_id,
            job_id=job_id,
            policy_version=POLICY_VERSION,
            evidence_type="attribute_comparison",
            evidence_data=summary,
        )
        .on_conflict_do_nothing(
            index_elements=[
                "match_id",
                "baseline_observation_id",
                "candidate_observation_id",
                "policy_version",
            ]
        )
    )


async def decision_evidence(session: AsyncSession, match_id: UUID) -> list[MatchEvidence]:
    return list(
        await session.scalars(
            select(MatchEvidence)
            .where(MatchEvidence.match_id == match_id)
            .order_by(MatchEvidence.created_at)
        )
    )
