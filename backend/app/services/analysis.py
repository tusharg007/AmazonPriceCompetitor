"""Freeze verified capture inputs; queue bounded reasoning; expose exact citations."""

import hashlib
import json
from copy import deepcopy
from datetime import UTC
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analysis.claims import PROMPT_VERSION, SCHEMA_VERSION, build_claims, numeric_comparable
from app.analysis.errors import AnalysisError
from app.analysis.provider import AnalysisProvider, GroqProvider
from app.core.config import Settings
from app.core.database import get_db_session
from app.core.exceptions import ApplicationError, NotFoundError
from app.models.entities import AnalysisRun, ProductObservation
from app.models.schemas import (
    AnalysisClaimResponse,
    AnalysisResponse,
    ClaimEvidenceDetail,
    CollectionJobRead,
    EvidenceArtifactRead,
)
from app.repository import analysis, catalog, jobs
from app.services.catalog import CatalogService
from app.services.evidence import read_verified_evidence
from app.services.records import observation_record


def input_hash(evidence: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


class AnalysisService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session, self.settings = session, settings

    async def record(self, product_id: int, observation_id: UUID) -> dict[str, Any]:
        product = await CatalogService(self.session, self.settings).require_product(product_id)
        observation = await self.session.get(ProductObservation, observation_id)
        if (
            observation is None
            or observation.product_id != product_id
            or not observation.evidence_artifact_id
        ):
            raise AnalysisError("Analysis requires stored observations with evidence artifacts.")
        if "_listing" not in observation.raw_metadata:
            raise AnalysisError(
                "Refresh this listing to freeze its title and brand before analysis."
            )
        artifact = await catalog.evidence(self.session, observation.evidence_artifact_id)
        if artifact is None or artifact.content_hash != observation.evidence_id:
            raise AnalysisError("Observation evidence is unavailable or inconsistent.")
        await read_verified_evidence(self.settings, EvidenceArtifactRead.model_validate(artifact))
        record = observation_record(product, observation)
        record["price_amount"] = (
            str(observation.price_amount) if observation.price_amount is not None else None
        )
        record["category_path"] = record.pop("categories")
        record["canonical_url"] = observation.canonical_url
        record["condition"] = observation.condition
        captured = observation.captured_at
        record["captured_at"] = (
            captured.replace(tzinfo=UTC) if captured.tzinfo is None else captured.astimezone(UTC)
        ).isoformat()
        record.pop("raw_metadata")
        return record

    async def build_input(self, product_id: int) -> dict[str, Any]:
        await CatalogService(self.session, self.settings).require_product(product_id)
        latest = (await catalog.latest_observations(self.session, [product_id])).get(product_id)
        if latest is None:
            raise AnalysisError("Collect a baseline product before requesting analysis.")
        baseline = await self.record(product_id, latest.id)
        candidates = []
        matches = await catalog.competitors(self.session, product_id, "confirmed", 0)
        for match in matches[: self.settings.max_competitors]:
            summary = match.evidence_summary
            if summary.get("baseline_observation_id") != str(latest.id):
                continue
            try:
                observation_id = UUID(summary["candidate_observation_id"])
            except (KeyError, ValueError, TypeError):
                continue
            candidate = await self.record(match.competitor_product_id, observation_id)
            if (
                candidate["domain"] != baseline["domain"]
                or candidate["geo_key"] != baseline["geo_key"]
            ):
                continue
            candidate.update(
                rank=match.search_rank,
                sponsored=match.sponsored,
                price_comparable=numeric_comparable(baseline, candidate),
            )
            candidates.append(candidate)
        if not candidates:
            raise AnalysisError(
                "Discover confirmed competitors for the current baseline capture before analysis."
            )
        collection_job = await jobs.get_job(self.session, latest.job_id) if latest.job_id else None
        return {
            "product": baseline,
            "competitors": candidates,
            "rules": {
                "analysis_policy_version": 3,
                "only_compare_matching_currency": True,
                "no_fx_conversion": True,
                "location_status": baseline["location_status"],
                "competitor_run_status": collection_job.status if collection_job else "unknown",
                "comparables_selected": len(candidates),
                "cohort": "saved confirmed matches; not the whole market",
            },
        }

    async def enqueue(self, product_id: int) -> CollectionJobRead:
        evidence = await self.build_input(product_id)
        digest = input_hash(evidence)
        completed = await analysis.find_run(
            self.session, product_id, digest, self.settings.groq_model
        )
        if not self.settings.groq_api_key and not (completed and completed.status == "succeeded"):
            raise ApplicationError(
                "Set APP_GROQ_API_KEY to enable analysis. Collection remains available.",
                "analysis_not_configured",
                503,
            )
        key = hashlib.sha256(
            f"{digest}:{self.settings.groq_model}:{PROMPT_VERSION}:{SCHEMA_VERSION}".encode()
        ).hexdigest()
        row = await jobs.enqueue(
            self.session,
            "analyze",
            product_id,
            key,
            {"evidence": evidence, "input_hash": digest, "model": self.settings.groq_model},
        )
        await self.session.commit()
        return CollectionJobRead.model_validate(row)

    async def detail(self, run_id: UUID) -> AnalysisResponse:
        run = await self.session.get(AnalysisRun, run_id)
        if run is None:
            raise NotFoundError("Analysis run")
        claims, sources = await analysis.claims_with_sources(self.session, run_id)
        by_claim: dict[UUID, list[ClaimEvidenceDetail]] = {}
        for link, observation, product in sources:
            by_claim.setdefault(link.claim_id, []).append(
                ClaimEvidenceDetail(
                    observation_id=observation.id,
                    product_id=product.id,
                    product_asin=product.asin,
                    price_text=observation.price_text,
                    captured_at=observation.captured_at,
                    source_url=observation.source_url,
                    collector=observation.collector,
                    extraction_method=observation.extraction_method,
                    evidence_id=observation.evidence_id,
                    evidence_artifact_id=observation.evidence_artifact_id,
                    role=link.role,
                )
            )
        return AnalysisResponse.model_validate(run, from_attributes=True).model_copy(
            update={
                "claims": [
                    AnalysisClaimResponse(
                        id=c.id,
                        claim_type=c.claim_type,
                        claim_text=c.claim_text,
                        claim_value=c.claim_value,
                        evidence=by_claim.get(c.id, []),
                    )
                    for c in claims
                ],
                "withheld_quantitative_claims": (run.raw_output or {}).get(
                    "withheld_quantitative_claims", 0
                ),
            }
        )


class AnalysisWorkerService:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        claim: jobs.ClaimedJob,
        provider: AnalysisProvider | None = None,
    ) -> None:
        self.factory, self.settings, self.claim = factory, settings, claim
        self.provider = provider or GroqProvider(settings)
        self.result = deepcopy(claim.result)

    async def run(self) -> None:
        request = self.result["request"]
        evidence, digest, model = request["evidence"], request["input_hash"], request["model"]
        if digest != input_hash(evidence):
            raise AnalysisError("Frozen analysis input failed its integrity check.")
        async with get_db_session(self.factory) as session:
            cached = await analysis.find_run(session, self.claim.product_id, digest, model)
            if cached and cached.status == "succeeded":
                self.result["analysis_id"] = str(cached.id)
                return
        try:
            if model != self.settings.groq_model:
                raise AnalysisError("Configured model changed since enqueue. Requeue the analysis.")
            parsed = await self.provider.generate(evidence)
            output, claims = build_claims(parsed, evidence)
        except AnalysisError as exc:
            async with get_db_session(self.factory) as session:
                await jobs.lock_owned_job(session, self.claim.id, self.claim.lease_token)
                failed = await analysis.save_run(
                    session,
                    self.claim.product_id,
                    self.claim.id,
                    digest,
                    model,
                    evidence,
                    None,
                    [],
                    str(exc),
                )
                self.result["analysis_id"] = str(failed.id)
            raise
        async with get_db_session(self.factory) as session:
            await jobs.lock_owned_job(session, self.claim.id, self.claim.lease_token)
            run = await analysis.save_run(
                session,
                self.claim.product_id,
                self.claim.id,
                digest,
                model,
                evidence,
                output,
                claims,
            )
            self.result["analysis_id"] = str(run.id)
