"""Deterministic matching policy and evidence-backed collection integration."""

from decimal import Decimal
from uuid import UUID

import pytest
from app.core.database import get_db_session
from app.matching.exclusions import select_comparable_competitors
from app.matching.scoring import classify_match, evaluate_match, normalized_attributes
from app.models.entities import CompetitorRelationship, MatchEvidence, ProductObservation
from app.services.matching import match_candidate
from app.worker.runner import CollectionWorker
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from backend.tests.test_api_postgres import persistence as persistence  # noqa: PLC0414 -- fixture
from backend.tests.test_worker import enqueue
from backend.tests.worker_fixtures import FixtureCollector
from src.relevance import select_comparable_competitors as v1_select


def record(**changes):
    return {
        "asin": "B000000001",
        "domain": "com",
        "geo_key": "__default__",
        "title": "Sony Wireless Headphones",
        "brand": "Visit the Sony Store",
        "categories": ["Electronics", "Headphones"],
        "price_amount": Decimal(100),
        "currency": "USD",
        "rating": 4.5,
        "attributes": {},
        **changes,
    }


def candidate(**changes):
    return record(asin="B000000002", **changes)


def test_obvious_strong_match_and_repeatability():
    first = evaluate_match(record(), candidate())
    assert first.status == "confirmed" and first.score == 1 and first.reason is None
    assert first == evaluate_match(record(), candidate())
    assert first.evidence["title_similarity"] == 1 and first.evidence["brand_score"] == 1


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"title": None}, "missing_title"),
        ({"title": "Headphones CAD version"}, "different_market_version"),
        ({"title": "Replacement case for Sony headphones"}, "compatibility_listing"),
        ({"currency": "INR"}, "currency_mismatch"),
        ({"price_amount": None}, "price_unavailable"),
        ({"price_amount": Decimal(10)}, "outside_comparable_price_band"),
        ({"variant": "large"}, "variant_mismatch"),
        ({"attributes": {"pack_size": "2"}}, "pack_size_mismatch"),
        ({"attributes": {"capacity": "2l"}}, "capacity_mismatch"),
        ({"attributes": {"product_type": "speakers"}}, "product_type_mismatch"),
        ({"sponsored": True}, "sponsored_listing"),
        ({"domain": "in"}, "marketplace_or_location_mismatch"),
    ],
)
def test_obvious_nonmatches(changes, reason):
    baseline = record(
        variant="small",
        attributes={"pack_size": "1", "capacity": "1l", "product_type": "headphones"},
    )
    decision = evaluate_match(baseline, candidate(**changes))
    assert decision.status == "rejected" and decision.score == 0 and decision.reason == reason


def test_missing_attributes_are_not_fabricated_and_ambiguous():
    decision = evaluate_match(
        record(brand=None, categories=[]), candidate(brand=None, categories=[])
    )
    assert decision.status == "ambiguous"
    assert decision.evidence["baseline"]["attributes"] == {}
    assert decision.evidence["brand_score"] == 0.5


def test_structured_normalization_and_explicit_pack_text():
    assert normalized_attributes(record(attributes={"capacity": "1 L", "quantity": 2})) == {
        "capacity": "1000ml",
        "pack_size": "2",
    }
    assert normalized_attributes(record(title="Headphones 2-pack"))["pack_size"] == "2"
    assert (
        evaluate_match(
            record(attributes={"capacity": "1 L"}), candidate(attributes={"capacity": "1000ml"})
        ).status
        == "confirmed"
    )


def test_dimensions_and_optional_jsonld_properties():
    assert (
        normalized_attributes(record(attributes={"size": "10 × 20 cm"}))["dimensions"] == "10x20cm"
    )
    assert (
        normalized_attributes(record(raw_metadata={"json_ld": {"additionalProperty": None}})) == {}
    )
    assert (
        normalized_attributes(
            record(
                raw_metadata={
                    "json_ld": {"additionalProperty": {"name": "capacity", "value": "1l"}}
                }
            )
        )["capacity"]
        == "1000ml"
    )


def test_classification_boundaries_and_v1_behavior_preserved():
    assert [classify_match(value) for value in [0, 0.299, 0.3, 0.699, 0.7, 1]] == [
        "rejected",
        "rejected",
        "ambiguous",
        "ambiguous",
        "confirmed",
        "confirmed",
    ]
    baseline, rows = record(), [candidate(), candidate(price_amount=None)]
    assert select_comparable_competitors(baseline, rows) == v1_select(baseline, rows)


@pytest.mark.asyncio
async def test_discovery_persists_scores_provenance_and_idempotent_audit(persistence):
    client, factory = persistence
    settings = client._transport.app.state.settings
    product, job = await enqueue(client, include=True)
    collector = FixtureCollector(settings)

    def titles(extracted, _evidence):
        pack = 2 if extracted.asin == "B000000003" else 1
        return extracted.model_copy(
            update={"title": f"Sony Wireless Headphones Pack of {pack}", "brand": "Sony"}
        )

    collector.product_mutator = titles
    async with CollectionWorker(factory, settings, lambda _: collector) as worker:
        assert await worker.run_once()
    detail = (await client.get(f"/api/jobs/{job['id']}")).json()
    assert detail["status"] == "succeeded", detail
    response = await client.get(f"/api/products/{product['id']}/competitors")
    matches = response.json()
    assert response.status_code == 200 and len(matches) == 2
    assert {row["match_status"] for row in matches} == {"confirmed", "rejected"}
    assert (
        len(
            (await client.get(f"/api/products/{product['id']}/competitors?status=confirmed")).json()
        )
        == 1
    )
    async with get_db_session(factory) as session:
        assert await session.scalar(select(func.count(MatchEvidence.id))) == 2
        for row in matches:
            summary = row["evidence_summary"]
            assert len(summary["sources"]) == 2
            assert all(source["evidence_artifact_id"] for source in summary["sources"])
            assert summary["search_evidence_artifact_id"]
            observation = await session.get(
                ProductObservation, UUID(summary["candidate_observation_id"])
            )
            await match_candidate(
                session,
                UUID(summary["baseline_observation_id"]),
                observation,
                UUID(job["id"]),
                {"rank": row["search_rank"]},
            )
        assert await session.scalar(select(func.count(CompetitorRelationship.id))) == 2
        assert await session.scalar(select(func.count(MatchEvidence.id))) == 2
    assert (
        await client.get(f"/api/products/{product['id']}/competitors?min_score=2")
    ).status_code == 422
    assert (await client.get("/api/products/9999/competitors")).status_code == 404


@pytest.mark.asyncio
async def test_failed_match_write_rolls_back_candidate_and_decision(persistence, monkeypatch):
    client, factory = persistence
    settings = client._transport.app.state.settings
    _, job = await enqueue(client, include=True)
    collector = FixtureCollector(settings)
    import app.services.matching as service

    original = service.save_decision

    async def fail(*args, **kwargs):
        await original(*args, **kwargs)
        raise OperationalError("private", {}, Exception("private"))

    monkeypatch.setattr(service, "save_decision", fail)
    async with CollectionWorker(factory, settings, lambda _: collector) as worker:
        await worker.run_once()
    detail = (await client.get(f"/api/jobs/{job['id']}")).json()
    assert detail["status"] == "partial" and "private" not in detail["error_message"]
    async with factory() as session:
        assert await session.scalar(select(func.count(ProductObservation.id))) == 1
        assert await session.scalar(select(func.count(MatchEvidence.id))) == 0
        assert await session.scalar(select(func.count(CompetitorRelationship.id))) == 0
