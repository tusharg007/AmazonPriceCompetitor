"""Frozen analysis API, numerical guardrails, queue execution and exact provenance."""

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from app.analysis.claims import build_claims, numeric_comparable
from app.analysis.errors import AnalysisError
from app.analysis.ported import LLMAnalysis, _normalize_analysis_payload
from app.core.exceptions import LeaseLostError
from app.models.entities import (
    AnalysisClaim,
    AnalysisRun,
    ClaimEvidence,
    CollectionJob,
    CompetitorRelationship,
    EvidenceArtifact,
    Product,
    ProductObservation,
)
from app.repository import jobs
from app.services.analysis import AnalysisService, AnalysisWorkerService, input_hash
from app.worker.runner import CollectionWorker
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker


async def seed(db_session, settings):
    settings.groq_api_key = "test-only-key"
    products = [
        Product(asin="B000000001", domain="com"),
        Product(asin="B000000002", domain="com", is_tracked=False),
    ]
    db_session.add_all(products)
    await db_session.flush()
    observations = []
    for index, p in enumerate(products):
        content = f"<html>Test listing {p.asin}</html>".encode()
        digest = hashlib.sha256(content).hexdigest()
        (settings.evidence_dir / f"{digest}.html").write_bytes(content)
        artifact = EvidenceArtifact(
            evidence_type="html",
            storage_path=f"{digest}.html",
            content_hash=digest,
            content_size_bytes=len(content),
            source_url=f"https://www.amazon.com/dp/{p.asin}",
            collector="playwright-v1",
            captured_at=datetime.now(UTC),
        )
        db_session.add(artifact)
        await db_session.flush()
        observation = ProductObservation(
            product_id=p.id,
            evidence_artifact_id=artifact.id,
            price_amount=Decimal(100) + index * 10,
            currency="USD",
            rating=4.5 - index / 10,
            source_url=artifact.source_url,
            captured_at=artifact.captured_at,
            collector=artifact.collector,
            extraction_method="json_ld",
            evidence_id=digest,
            raw_metadata={"_listing": {"title": "Sony Wireless Headphones", "brand": "Sony"}},
        )
        db_session.add(observation)
        await db_session.flush()
        observations.append(observation)
    db_session.add(
        CompetitorRelationship(
            baseline_product_id=products[0].id,
            competitor_product_id=products[1].id,
            match_status="confirmed",
            match_score=0.9,
            evidence_summary={
                "baseline_observation_id": str(observations[0].id),
                "candidate_observation_id": str(observations[1].id),
            },
        )
    )
    await db_session.commit()
    return products, observations


class Provider:
    def __init__(self, error=False):
        self.calls = 0
        self.error = error

    async def generate(self, evidence):
        self.calls += 1
        if self.error:
            raise AnalysisError("Provider unavailable; retry analysis.")
        return LLMAnalysis(
            summary="This is a filtered comparison of saved listing evidence.",
            positioning="The listings describe similar product positioning.",
            top_competitors=[
                {
                    "asin": evidence["competitors"][0]["asin"],
                    "key_points": ["Review the captured listing before deciding."],
                }
            ],
            recommendations=["Verify listing claims at the source."],
        )


@pytest.mark.asyncio
async def test_analysis_api_worker_claim_links_and_dedup(
    async_client, db_session, test_settings, test_engine
):
    products, observations = await seed(db_session, test_settings)
    provider = Provider()
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    first = await async_client.post(f"/api/products/{products[0].id}/analyze")
    assert first.status_code == 202, first.text
    duplicate = await async_client.post(f"/api/products/{products[0].id}/analyze")
    assert first.json()["id"] == duplicate.json()["id"]

    def no_browser(_):
        raise AssertionError("Analysis must not create a browser")

    async with CollectionWorker(factory, test_settings, no_browser, provider) as worker:
        assert await worker.run_once()
        job = (await async_client.get(f"/api/jobs/{first.json()['id']}")).json()
        assert job["status"] == "succeeded", job
        run_id = job["result"]["analysis_id"]
        run = (await async_client.get(f"/api/analyses/{run_id}")).json()
        assert run["status"] == "succeeded"
        assert (await async_client.get(f"/api/analyses/{run_id}/claims")).json() == run["claims"]
        assert len(run["claims"]) == 6
        for claim in run["claims"]:
            assert {s["observation_id"] for s in claim["evidence"]} == {
                str(o.id) for o in observations
            }
            assert all(
                s["captured_at"].endswith("Z") and s["extraction_method"] and s["evidence_id"]
                for s in claim["evidence"]
            )
        numerical = next(c for c in run["claims"] if c["claim_type"] == "price_comparison")
        assert numerical["claim_value"]["difference"] == "10.0000"
        await async_client.post(f"/api/products/{products[0].id}/analyze")
        assert await worker.run_once()
        assert provider.calls == 1
    assert await db_session.scalar(select(func.count(AnalysisRun.id))) == 1


@pytest.mark.asyncio
async def test_failed_analysis_is_recorded_and_manual_retry_succeeds(
    async_client, db_session, test_settings, test_engine
):
    products, _ = await seed(db_session, test_settings)
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    provider = Provider(True)
    response = await async_client.post(f"/api/products/{products[0].id}/analyze")
    async with CollectionWorker(factory, test_settings, analysis_provider=provider) as worker:
        await worker.run_once()
        job = (await async_client.get(f"/api/jobs/{response.json()['id']}")).json()
        assert job["status"] == "failed" and job["error_code"] == "analysis_failed"
        failure = (await async_client.get(f"/api/analyses/{job['result']['analysis_id']}")).json()
        assert failure["status"] == "failed" and failure["claims"] == []
        provider.error = False
        await async_client.post(f"/api/products/{products[0].id}/analyze")
        await worker.run_once()
    assert await db_session.scalar(select(func.count(AnalysisRun.id))) == 1


@pytest.mark.asyncio
async def test_analysis_missing_key_stale_match_and_no_capture(
    async_client, db_session, test_settings
):
    products, observations = await seed(db_session, test_settings)
    test_settings.groq_api_key = None
    response = await async_client.post(f"/api/products/{products[0].id}/analyze")
    assert response.status_code == 503 and response.json()["error"] == "analysis_not_configured"
    test_settings.groq_api_key = "test-only"
    await db_session.execute(
        update(CompetitorRelationship).values(
            evidence_summary={
                "baseline_observation_id": str(uuid4()),
                "candidate_observation_id": str(observations[1].id),
            }
        )
    )
    await db_session.commit()
    response = await async_client.post(f"/api/products/{products[0].id}/analyze")
    assert response.status_code == 409 and "confirmed competitors" in response.json()["detail"]
    empty = (await async_client.post("/api/products", json={"asin": "B000000003"})).json()
    assert (await async_client.post(f"/api/products/{empty['id']}/analyze")).status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path,status",
    [
        ("post", "/api/products/999/analyze", 404),
        ("post", "/api/products/bad/analyze", 422),
        ("get", "/api/analyses/bad", 422),
        ("get", "/api/analyses/00000000-0000-0000-0000-000000000001", 404),
    ],
)
async def test_analysis_errors(async_client, method, path, status):
    assert (await async_client.request(method, path)).status_code == status


@pytest.mark.asyncio
async def test_frozen_input_integrity_and_stale_lease(db_session, test_settings, test_engine):
    products, _ = await seed(db_session, test_settings)
    await AnalysisService(db_session, test_settings).enqueue(products[0].id)
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as session:
        claim = await jobs.claim_next_job(session, 90, 300)
        await session.commit()
    assert claim
    provider = Provider()
    claim.result["request"]["input_hash"] = "tampered"
    with pytest.raises(AnalysisError, match="integrity"):
        await AnalysisWorkerService(factory, test_settings, claim, provider).run()
    assert provider.calls == 0


def test_numerical_boundary_unknown_asins_and_currency():
    a = {
        "asin": "B000000001",
        "observation_id": str(uuid4()),
        "price_amount": "100.00",
        "currency": "USD",
        "domain": "com",
        "geo_key": "__default__",
        "location_status": "default",
        "rating": None,
    }
    b = a | {"asin": "B000000002", "observation_id": str(uuid4()), "price_amount": "110.00"}
    parsed = _normalize_analysis_payload(
        {
            "summary": "Filtered saved evidence.",
            "positioning": "The price is $999 cheaper.",
            "recommendations": "Review source evidence.",
            "top_competitors": [{"asin": b["asin"], "key_points": "Price is 20% lower."}],
        }
    )
    output, claims = build_claims(parsed, {"product": a, "competitors": [b]})
    assert output["withheld_quantitative_claims"] == 2
    assert all("$999" not in c["claim_text"] and "20%" not in c["claim_text"] for c in claims)
    assert not numeric_comparable(a, b | {"currency": "INR"})
    assert not numeric_comparable(a, b | {"location_status": "unverified"})
    parsed.top_competitors[0].asin = "B999999999"
    with pytest.raises(AnalysisError, match="unsupported"):
        build_claims(parsed, {"product": a, "competitors": [b]})
    assert input_hash({"a": 1, "b": 2}) == input_hash({"b": 2, "a": 1})


@pytest.mark.asyncio
async def test_analysis_cannot_publish_after_lease_replaced(db_session, test_settings, test_engine):
    products, _ = await seed(db_session, test_settings)
    await AnalysisService(db_session, test_settings).enqueue(products[0].id)
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as session:
        claim = await jobs.claim_next_job(session, 90, 300)
        await session.commit()
    assert claim
    await db_session.execute(
        update(CollectionJob).where(CollectionJob.id == claim.id).values(lease_token="replacement")
    )
    await db_session.commit()
    with pytest.raises(LeaseLostError):
        await AnalysisWorkerService(factory, test_settings, claim, Provider()).run()
    assert await db_session.scalar(select(func.count(AnalysisRun.id))) == 0


@pytest.mark.asyncio
async def test_claim_fk_failure_rolls_back_all_analysis_writes(db_session, test_settings):
    from app.repository.analysis import save_run

    products, _ = await seed(db_session, test_settings)
    evidence = await AnalysisService(db_session, test_settings).build_input(products[0].id)
    with pytest.raises(IntegrityError):
        await save_run(
            db_session,
            products[0].id,
            None,
            input_hash(evidence),
            "test-model",
            evidence,
            {},
            [
                {
                    "claim_type": "summary",
                    "claim_text": "test",
                    "claim_value": {"origin": "llm_interpretation"},
                    "sources": [{"observation_id": str(uuid4()), "role": "baseline"}],
                }
            ],
        )
    await db_session.rollback()
    assert await db_session.scalar(select(func.count(AnalysisRun.id))) == 0
    assert await db_session.scalar(select(func.count(AnalysisClaim.id))) == 0
    assert await db_session.scalar(select(func.count(ClaimEvidence.claim_id))) == 0
