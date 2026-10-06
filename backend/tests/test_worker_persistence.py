"""Queue and append-only storage behavior on both supported database backends."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from app.core.database import get_db_session
from app.core.exceptions import LeaseLostError
from app.models.entities import CollectionJob, EvidenceArtifact, ProductObservation
from app.repository import jobs, observations
from app.services.collection import CollectionService
from app.worker.runner import CollectionWorker
from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError

from backend.tests.test_api_postgres import (
    persistence as persistence,  # noqa: PLC0414 -- shared fixture
)
from backend.tests.test_worker import enqueue
from backend.tests.worker_fixtures import FixtureCollector


@pytest.mark.asyncio
async def test_concurrent_claims_fence_and_recover(persistence):
    client, factory = persistence
    settings = client._transport.app.state.settings
    for number in range(1, 5):
        await enqueue(client, asin=f"B00000000{number}")

    async def claim():
        async with get_db_session(factory) as session:
            return await jobs.claim_next_job(session, 90, 300)

    claims = [row for row in await asyncio.gather(*(claim() for _ in range(8))) if row]
    assert len(claims) == 4 and len({claim.id for claim in claims}) == 4
    old = claims[0]
    async with get_db_session(factory) as session:
        await session.execute(
            update(CollectionJob)
            .where(CollectionJob.id == old.id)
            .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=10))
        )
    new = await claim()
    assert new.id == old.id and new.lease_token != old.lease_token and new.attempts == 2
    async with get_db_session(factory) as session:
        assert not await jobs.heartbeat(session, old, 90)
        assert not await jobs.finish_job(session, old, "succeeded", {"stale": True})
    collector = FixtureCollector(settings)
    extracted, evidence = await collector.collect_product(old.asin, old.domain)
    stale_service = CollectionService(factory, settings, collector, old)
    with pytest.raises(LeaseLostError):
        await stale_service.save_product(extracted, evidence, baseline=True)
    async with get_db_session(factory) as session:
        assert await session.scalar(select(func.count(ProductObservation.id))) == 0
        assert await session.scalar(select(func.count(EvidenceArtifact.id))) == 0
        assert await jobs.finish_job(session, new, "succeeded", {"current": True})
    detail = (await client.get(f"/api/jobs/{new.id}")).json()
    assert detail["result"] == {"current": True}


@pytest.mark.asyncio
async def test_lease_exhaustion_and_unexpired_job_not_reclaimed(persistence):
    client, factory = persistence
    _, job = await enqueue(client)
    async with get_db_session(factory) as session:
        claim = await jobs.claim_next_job(session, 90, 300)
    async with get_db_session(factory) as session:
        assert await jobs.claim_next_job(session, 90, 300) is None
        await session.execute(
            update(CollectionJob)
            .where(CollectionJob.id == claim.id)
            .values(attempts=2, lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    async with get_db_session(factory) as session:
        assert await jobs.claim_next_job(session, 90, 300) is None
    detail = (await client.get(f"/api/jobs/{job['id']}")).json()
    assert detail["status"] == "failed" and detail["error_code"] == "attempts_exhausted"
    assert detail["progress"] == 100 and detail["finished_at"]


@pytest.mark.asyncio
async def test_worker_appends_once_per_capture_and_transaction_rollback(persistence, monkeypatch):
    client, factory = persistence
    settings = client._transport.app.state.settings
    _product, job = await enqueue(client)
    async with get_db_session(factory) as session:
        claim = await jobs.claim_next_job(session, 90, 300)
    collector = FixtureCollector(settings)
    extracted, evidence = await collector.collect_product(claim.asin, claim.domain)
    service = CollectionService(factory, settings, collector, claim)
    first = await service.save_product(extracted, evidence, baseline=True)
    assert await service.save_product(extracted, evidence, baseline=True) == first
    async with get_db_session(factory) as session:
        assert await session.scalar(select(func.count(ProductObservation.id))) == 1
        assert await session.scalar(select(func.count(EvidenceArtifact.id))) == 1
    # Fail after an INSERT; both the new observation and new artifact must roll back.
    original = observations.append_observation

    async def fail_after_insert(*args, **kwargs):
        await original(*args, **kwargs)
        raise OperationalError("secret insert", {}, Exception("secret storage"))

    monkeypatch.setattr(observations, "append_observation", fail_after_insert)
    extracted, evidence = await collector.collect_product(claim.asin, claim.domain)
    with pytest.raises(OperationalError):
        await service.save_product(extracted, evidence, baseline=True)
    assert service.result["observation_ids"] == [first]
    async with get_db_session(factory) as session:
        assert await session.scalar(select(func.count(ProductObservation.id))) == 1
        assert await session.scalar(select(func.count(EvidenceArtifact.id))) == 1
        stored = await session.get(CollectionJob, UUID(job["id"]))
        assert stored.result["observation_ids"] == [first]


@pytest.mark.asyncio
async def test_worker_completion_evidence_api_both_backends(persistence):
    client, factory = persistence
    settings = client._transport.app.state.settings
    _product, job = await enqueue(client, include=True)
    collector = FixtureCollector(settings)
    async with CollectionWorker(factory, settings, lambda _: collector) as worker:
        assert await worker.run_once()
    detail = (await client.get(f"/api/jobs/{job['id']}")).json()
    assert detail["status"] == "succeeded"
    assert len(detail["result"]["observation_ids"]) == 3
    assert (await client.get("/api/products")).json()["total"] == 1
    for evidence_id in detail["result"]["evidence_artifact_ids"]:
        assert (await client.get(f"/api/evidence/{evidence_id}/content")).status_code == 200


@pytest.mark.asyncio
async def test_postgresql_skip_locked_claims_another_row(persistence):
    client, factory = persistence
    if factory.kw["bind"].dialect.name != "postgresql":
        return  # SQLite uses serialized atomic UPDATE; SKIP LOCKED is PostgreSQL-specific.
    _, first = await enqueue(client, asin="B000000001")
    _, second = await enqueue(client, asin="B000000002")
    async with factory() as locked:
        await locked.scalar(
            select(CollectionJob).where(CollectionJob.id == UUID(first["id"])).with_for_update()
        )
        async with get_db_session(factory) as session:
            claim = await asyncio.wait_for(jobs.claim_next_job(session, 90, 300), 5)
            assert str(claim.id) == second["id"]
        await locked.rollback()
