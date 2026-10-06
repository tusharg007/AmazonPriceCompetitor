"""Worker ownership, completion, retry, cancellation and evidence persistence."""

import asyncio
import uuid

import pytest
from app.collector.errors import PageNotFoundError, ScrapingBlockedError, ScrapingError
from app.models.entities import (
    CollectionJob,
    CompetitorRelationship,
    EvidenceArtifact,
    ProductObservation,
)
from app.models.enums import ScrapeErrorCode
from app.repository import jobs
from app.worker.runner import CollectionWorker
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.tests.worker_fixtures import FixtureCollector


async def enqueue(client, include=False, asin="B09XS7JWHH", domain="com", scan=False):
    product = (await client.post("/api/products", json={"asin": asin, "domain": domain})).json()
    path = f"/api/products/{product['id']}/" + ("competitors/scan" if scan else "collect")
    response = await client.post(path, json=None if scan else {"include_competitors": include})
    assert response.status_code == 202
    return product, response.json()


@pytest.mark.asyncio
async def test_api_to_worker_history_and_later_capture(
    async_client, test_engine, test_settings, db_session
):
    product, job = await enqueue(async_client)
    collector = FixtureCollector(test_settings)
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with CollectionWorker(factory, test_settings, lambda _: collector) as worker:
        assert await worker.run_once()
        complete = (await async_client.get(f"/api/jobs/{job['id']}")).json()
        assert complete["status"] == "succeeded" and complete["progress"] == 100
        assert complete["attempts"] == 1 and len(complete["result"]["observation_ids"]) == 1
        assert not await worker.run_once()
        _, second = await enqueue(async_client)
        assert await worker.run_once()
        assert collector.entered == 1
    assert collector.closed
    history = (await async_client.get(f"/api/products/{product['id']}/observations")).json()
    assert len(history) == 2 and history[0]["evidence_id"] == history[1]["evidence_id"]
    assert history[0]["captured_at"] != history[1]["captured_at"]
    for observation in history:
        assert observation["job_id"] in (job["id"], second["id"])
        assert all(
            observation[field]
            for field in (
                "source_url",
                "captured_at",
                "collector",
                "extraction_method",
                "evidence_id",
            )
        )
        evidence = await async_client.get(
            f"/api/evidence/{observation['evidence_artifact_id']}/content"
        )
        assert evidence.status_code == 200 and b"Fixture B09XS7JWHH" in evidence.content
    row = await db_session.get(CollectionJob, uuid.UUID(job["id"]))
    assert row.lease_token is None and row.lease_expires_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,code,retry",
    [
        (ScrapingBlockedError("blocked"), "blocked", False),
        (PageNotFoundError("absent"), "not_found", False),
        (ScrapingError(ScrapeErrorCode.TIMEOUT, "timeout"), "timeout", True),
        (RuntimeError("secret internal exception"), "parse_error", False),
    ],
)
async def test_failures_and_bounded_retry(
    async_client, test_engine, test_settings, failure, code, retry
):
    product, job = await enqueue(async_client)
    collector = FixtureCollector(test_settings)
    collector.failure = failure
    async with CollectionWorker(
        async_sessionmaker(test_engine, expire_on_commit=False), test_settings, lambda _: collector
    ) as worker:
        assert await worker.run_once()
        detail = (await async_client.get(f"/api/jobs/{job['id']}")).json()
        assert detail["status"] == ("queued" if retry else "failed")
        if retry:
            assert await worker.run_once()
        detail = (await async_client.get(f"/api/jobs/{job['id']}")).json()
        assert detail["status"] == "failed" and detail["error_code"] == code
        assert detail["attempts"] == (2 if retry else 1)
        assert "secret" not in detail["error_message"]
    assert (await async_client.get(f"/api/products/{product['id']}/observations")).json() == []
    if code == "blocked":
        assert (
            await async_client.post(f"/api/products/{product['id']}/collect")
        ).status_code == 429


@pytest.mark.asyncio
async def test_startup_failure_is_recorded_and_retry_budget_consumed(
    async_client, test_engine, test_settings
):
    _, job = await enqueue(async_client)
    collector = FixtureCollector(test_settings)
    collector.startup_failure = RuntimeError("launch")
    async with CollectionWorker(
        async_sessionmaker(test_engine, expire_on_commit=False), test_settings, lambda _: collector
    ) as worker:
        assert await worker.run_once() and await worker.run_once()
        assert not await worker.run_once()
    detail = (await async_client.get(f"/api/jobs/{job['id']}")).json()
    assert detail["status"] == "failed" and detail["error_code"] == "browser_error"
    assert detail["attempts"] == 2


@pytest.mark.asyncio
async def test_raw_discovery_partial_does_not_add_matches_or_track_candidates(
    async_client, test_engine, test_settings, db_session
):
    _, job = await enqueue(async_client, scan=True)
    collector = FixtureCollector(test_settings)
    collector.candidate_failure = PageNotFoundError("absent")
    async with CollectionWorker(
        async_sessionmaker(test_engine, expire_on_commit=False), test_settings, lambda _: collector
    ) as worker:
        assert await worker.run_once()
    detail = (await async_client.get(f"/api/jobs/{job['id']}")).json()
    assert detail["status"] == "partial" and detail["error_code"] == "not_found"
    assert len(detail["result"]["observation_ids"]) == 2
    assert len(detail["result"]["candidates"]) == 2
    assert len(detail["result"]["evidence_artifact_ids"]) == 4
    assert (await async_client.get("/api/products")).json()["total"] == 1
    assert (await async_client.get("/api/products?tracked_only=false")).json()["total"] == 2
    assert await db_session.scalar(select(func.count(CompetitorRelationship.id))) == 0
    assert [call[0] for call in collector.calls] == ["B09XS7JWHH", "B000000002", "B000000003"]
    for candidate in detail["result"]["candidates"]:
        metadata = (
            await async_client.get(f"/api/evidence/{candidate['search_evidence_artifact_id']}")
        ).json()
        assert metadata["content_hash"] == candidate["provenance"]["evidence_id"]


@pytest.mark.asyncio
async def test_search_block_retains_earlier_metadata_and_stops_navigation(
    async_client, test_engine, test_settings
):
    _, job = await enqueue(async_client, include=True)
    collector = FixtureCollector(test_settings)
    collector.search_failure = ScrapingBlockedError("search blocked")
    async with CollectionWorker(
        async_sessionmaker(test_engine, expire_on_commit=False), test_settings, lambda _: collector
    ) as worker:
        await worker.run_once()
    detail = (await async_client.get(f"/api/jobs/{job['id']}")).json()
    assert detail["status"] == "partial" and detail["error_code"] == "blocked"
    assert len(detail["result"]["observation_ids"]) == 1
    assert len(detail["result"]["evidence_artifact_ids"]) == 3
    assert len(collector.calls) == 1


@pytest.mark.asyncio
async def test_heartbeat_no_connection_held_across_browser_wait(
    async_client, test_engine, test_settings, monkeypatch
):
    _, job = await enqueue(async_client)
    settings = test_settings.model_copy(
        update={"worker_heartbeat_seconds": 0.05, "worker_lease_seconds": 3}
    )
    collector = FixtureCollector(settings)
    collector.release = asyncio.Event()
    renewed = asyncio.Event()
    original = jobs.heartbeat

    async def heartbeat(*args, **kwargs):
        outcome = await original(*args, **kwargs)
        renewed.set()
        return outcome

    monkeypatch.setattr(jobs, "heartbeat", heartbeat)
    async with CollectionWorker(
        async_sessionmaker(test_engine, expire_on_commit=False), settings, lambda _: collector
    ) as worker:
        task = asyncio.create_task(worker.run_once())
        await asyncio.wait_for(collector.started.wait(), 5)
        await asyncio.wait_for(renewed.wait(), 5)

        # Heartbeat commits before the next browser step; it doesn't retain a session while waiting.
        async def wait_for_release():
            while test_engine.pool.checkedout():
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_for_release(), 2)
        assert test_engine.pool.checkedout() == 0
        collector.release.set()
        assert await task
    assert (await async_client.get(f"/api/jobs/{job['id']}")).json()["status"] == "succeeded"


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [True, False])
async def test_cancellation_or_lease_loss_cancels_collection(
    async_client, test_engine, test_settings, db_session, cancel
):
    product, job = await enqueue(async_client)
    settings = test_settings.model_copy(
        update={"worker_heartbeat_seconds": 0.1, "worker_lease_seconds": 3}
    )
    collector = FixtureCollector(settings)
    collector.release = asyncio.Event()
    async with CollectionWorker(
        async_sessionmaker(test_engine, expire_on_commit=False), settings, lambda _: collector
    ) as worker:
        task = asyncio.create_task(worker.run_once())
        await asyncio.wait_for(collector.started.wait(), 5)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await db_session.execute(
                update(CollectionJob)
                .where(CollectionJob.id == uuid.UUID(job["id"]))
                .values(lease_token="replacement")
            )
            await db_session.commit()
            assert await asyncio.wait_for(task, 5)
    assert collector.cancelled and collector.closed
    detail = (await async_client.get(f"/api/jobs/{job['id']}")).json()
    assert detail["status"] == ("cancelled" if cancel else "running")
    assert (await async_client.get(f"/api/products/{product['id']}/observations")).json() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("tampering", ["provenance", "title", "missing_file"])
async def test_invalid_evidence_never_publishes_success(
    async_client, test_engine, test_settings, db_session, tampering
):
    _, job = await enqueue(async_client)
    collector = FixtureCollector(test_settings)

    def mutate(product, evidence):
        if tampering == "provenance":
            return product.model_copy(
                update={
                    "provenance": product.provenance.model_copy(update={"evidence_id": "invalid"})
                }
            )
        if tampering == "title":
            return product.model_copy(update={"title": None})
        (test_settings.evidence_dir / evidence.storage_path).unlink()
        return product

    collector.product_mutator = mutate
    async with CollectionWorker(
        async_sessionmaker(test_engine, expire_on_commit=False), test_settings, lambda _: collector
    ) as worker:
        await worker.run_once()
    assert (await async_client.get(f"/api/jobs/{job['id']}")).json()["status"] == "failed"
    assert await db_session.scalar(select(func.count(ProductObservation.id))) == 0
    assert await db_session.scalar(select(func.count(EvidenceArtifact.id))) == 0


@pytest.mark.asyncio
async def test_queue_skips_cooling_marketplace(async_client, test_engine, test_settings):
    _, first = await enqueue(async_client)
    _, waiting = await enqueue(async_client, asin="B000000002")
    _, eligible = await enqueue(async_client, asin="B000000003", domain="ca")
    collector = FixtureCollector(test_settings)
    collector.failure = ScrapingBlockedError("blocked")
    async with CollectionWorker(
        async_sessionmaker(test_engine, expire_on_commit=False), test_settings, lambda _: collector
    ) as worker:
        await worker.run_once()
        collector.failure = None
        assert await worker.run_once()
        assert not await worker.run_once()
    assert (await async_client.get(f"/api/jobs/{first['id']}")).json()["status"] == "failed"
    assert (await async_client.get(f"/api/jobs/{waiting['id']}")).json()["status"] == "queued"
    assert (await async_client.get(f"/api/jobs/{eligible['id']}")).json()["status"] == "succeeded"
