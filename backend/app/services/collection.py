"""Real scrape -> verified evidence -> append-only observation orchestration."""

from copy import deepcopy
from dataclasses import asdict
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeout
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.collector.amazon import AmazonCollector
from app.collector.base import EvidenceArtifactData
from app.collector.errors import ScrapingError
from app.core.config import Settings
from app.core.database import get_db_session
from app.core.exceptions import EvidenceError, LeaseLostError
from app.core.validation import amazon_identity
from app.models.enums import ScrapeErrorCode
from app.models.schemas import EvidenceArtifactRead, ExtractedProduct, ExtractedSearchCandidate
from app.repository import catalog, jobs, observations
from app.services.evidence import read_verified_evidence


def collection_error(exc: Exception) -> ScrapingError:
    if isinstance(exc, ScrapingError):
        return exc
    if isinstance(exc, (PlaywrightTimeout, TimeoutError)):
        return ScrapingError(ScrapeErrorCode.TIMEOUT, "Product collection timed out")
    if isinstance(exc, PlaywrightError):
        return ScrapingError(ScrapeErrorCode.BROWSER_ERROR, "Browser collection failed")
    if isinstance(exc, (SQLAlchemyError, OSError, EvidenceError)):
        return ScrapingError(
            ScrapeErrorCode.UNAVAILABLE, "Collection storage is unavailable or evidence is invalid"
        )
    if isinstance(exc, ValueError):
        return ScrapingError(
            ScrapeErrorCode.INVALID_INPUT, "Collection input or resolved product is invalid"
        )
    return ScrapingError(
        ScrapeErrorCode.PARSE_ERROR, "Product collection could not extract valid evidence"
    )


class CollectionService:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        collector: AmazonCollector,
        claim: jobs.ClaimedJob,
    ) -> None:
        self.factory, self.settings, self.collector, self.claim = (
            factory,
            settings,
            collector,
            claim,
        )
        self.result: dict[str, Any] = deepcopy(claim.result)
        self.result.setdefault("observation_ids", [])
        self.result.setdefault("evidence_artifact_ids", [])
        self.result["candidates"] = []
        self.result["failures"] = []

    async def verify(self, evidence: EvidenceArtifactData) -> None:
        parsed = urlsplit(evidence.source_url)
        if parsed.scheme != "https" or parsed.hostname not in (
            f"amazon.{self.claim.domain}",
            f"www.amazon.{self.claim.domain}",
        ):
            raise ScrapingError(
                ScrapeErrorCode.PARSE_ERROR, "Evidence came from an unexpected marketplace"
            )
        await read_verified_evidence(
            self.settings, EvidenceArtifactRead(id=uuid4(), **asdict(evidence))
        )

    async def checkpoint(self, progress: int) -> None:
        async with get_db_session(self.factory) as session:
            row = await jobs.lock_owned_job(session, self.claim.id, self.claim.lease_token)
            row.result = deepcopy(self.result)
            row.progress = max(row.progress, progress)

    async def save_product(
        self, extracted: ExtractedProduct, evidence: EvidenceArtifactData, baseline: bool
    ) -> str:
        asin, domain = amazon_identity(evidence.source_url)
        provenance = extracted.provenance
        if (
            asin != extracted.asin
            or domain != self.claim.domain
            or extracted.domain != domain
            or (baseline and asin != self.claim.asin)
            or provenance.source_url != evidence.source_url
            or provenance.timestamp != evidence.captured_at
            or provenance.evidence_id != evidence.content_hash
            or provenance.collector != evidence.collector
            or not extracted.title
            or not extracted.title.strip()
        ):
            raise ScrapingError(
                ScrapeErrorCode.PARSE_ERROR,
                "Product identity, title or provenance does not match captured evidence",
            )
        await self.verify(evidence)
        result = deepcopy(self.result)
        async with get_db_session(self.factory) as session:
            job = await jobs.lock_owned_job(session, self.claim.id, self.claim.lease_token)
            if baseline:
                product = await catalog.get_product(session, self.claim.product_id)
                if product is None:
                    raise ScrapingError(
                        ScrapeErrorCode.NOT_FOUND, "Tracked product no longer exists"
                    )
            else:
                product, _ = await catalog.get_or_create_product(
                    session,
                    asin,
                    domain,
                    self.claim.geo_key,
                    self.claim.requested_location,
                    tracked=False,
                )
            observation = await observations.append_observation(
                session, product, extracted, evidence, self.claim.id
            )
            identifier = str(observation.id)
            if identifier not in result["observation_ids"]:
                result["observation_ids"].append(identifier)
            artifact_id = str(observation.evidence_artifact_id)
            if artifact_id not in result["evidence_artifact_ids"]:
                result["evidence_artifact_ids"].append(artifact_id)
            if baseline:
                result["baseline_observation_id"] = identifier
            else:
                for candidate in result["candidates"]:
                    if candidate["asin"] == asin:
                        candidate.update(product_id=product.id, observation_id=identifier)
            job.result = deepcopy(result)
            job.progress = max(job.progress, 30)
        self.result = result
        return identifier

    async def save_search(
        self, candidates: list[ExtractedSearchCandidate], evidence: list[EvidenceArtifactData]
    ) -> None:
        for artifact in evidence:
            await self.verify(artifact)
        result = deepcopy(self.result)
        async with get_db_session(self.factory) as session:
            job = await jobs.lock_owned_job(session, self.claim.id, self.claim.lease_token)
            mapping = {}
            for artifact in evidence:
                row = await observations.save_artifact(session, artifact)
                mapping[(artifact.content_hash, artifact.captured_at)] = (str(row.id), artifact)
                result["evidence_artifact_ids"].append(str(row.id))
            for candidate in candidates:
                provenance = candidate.provenance
                match = mapping.get((provenance.evidence_id, provenance.timestamp))
                if (
                    match is None
                    or provenance.source_url != match[1].source_url
                    or provenance.collector != match[1].collector
                ):
                    raise ScrapingError(
                        ScrapeErrorCode.PARSE_ERROR,
                        "Search candidate has no matching captured evidence",
                    )
                result["candidates"].append(
                    {**candidate.model_dump(mode="json"), "search_evidence_artifact_id": match[0]}
                )
            job.result = deepcopy(result)
            job.progress = max(job.progress, 40)
        self.result = result

    def selected_candidates(
        self, candidates: list[ExtractedSearchCandidate]
    ) -> list[ExtractedSearchCandidate]:
        selected: list[ExtractedSearchCandidate] = []
        seen = {self.claim.asin}
        for candidate in candidates:
            if candidate.sponsored or candidate.asin in seen:
                continue
            selected.append(candidate)
            seen.add(candidate.asin)
            if len(selected) >= self.settings.max_competitors:
                break
        return selected

    async def run(self) -> None:
        options = self.result.get("request", {})
        if not isinstance(options, dict) or not isinstance(
            options.get("include_competitors", False), bool
        ):
            raise ScrapingError(ScrapeErrorCode.INVALID_INPUT, "Invalid stored collection request")
        if self.claim.kind not in ("scrape_product", "discover_competitors"):
            raise ScrapingError(ScrapeErrorCode.INVALID_INPUT, "Unsupported collection job kind")
        await self.checkpoint(5)
        extracted, artifact = await self.collector.collect_product(
            self.claim.asin, self.claim.domain, self.claim.requested_location
        )
        await self.save_product(extracted, artifact, baseline=True)
        if self.claim.kind != "discover_competitors" and not options.get(
            "include_competitors", False
        ):
            return
        assert extracted.title is not None
        self.result["search_query"] = extracted.title
        try:
            candidates, last_evidence = await self.collector.search_competitors(
                extracted.title, self.claim.domain, max_pages=self.settings.max_search_pages
            )
        except Exception:
            # A challenge on page two must not discard page one's evidence metadata.
            assets = getattr(self.collector, "search_evidence", [])
            if assets:
                await self.save_search(
                    self.selected_candidates(getattr(self.collector, "search_candidates", [])),
                    assets,
                )
            raise
        selected = self.selected_candidates(candidates)
        await self.save_search(
            selected, getattr(self.collector, "search_evidence", [last_evidence])
        )
        for index, candidate in enumerate(selected):
            try:
                extracted, artifact = await self.collector.collect_product(
                    candidate.asin, self.claim.domain, self.claim.requested_location
                )
                if extracted.asin != candidate.asin:
                    raise ScrapingError(
                        ScrapeErrorCode.VARIANT_MISMATCH, "Resolved candidate has a different ASIN"
                    )
                await self.save_product(extracted, artifact, baseline=False)
            except (SQLAlchemyError, LeaseLostError):
                raise
            except Exception as exc:
                error = collection_error(exc)
                self.result["failures"].append(
                    {"asin": candidate.asin, "code": error.code.value, "message": str(error)}
                )
                if error.code == ScrapeErrorCode.BLOCKED:
                    raise error from exc
            await self.checkpoint(50 + int(45 * (index + 1) / len(selected)))
