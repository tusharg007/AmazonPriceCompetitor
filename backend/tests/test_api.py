"""Phase 2 HTTP contracts, durable writes and error-path regressions."""

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.models.entities import (
    CollectionJob,
    CompetitorRelationship,
    EvidenceArtifact,
    Product,
    ProductObservation,
)
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession


async def register(client, **values):
    response = await client.post("/api/products", json={"asin": "B09XS7JWHH", **values})
    assert response.status_code in (200, 201), response.text
    return response.json()


@pytest.mark.asyncio
async def test_register_dedup_url_geo_and_retrack(async_client):
    first = await register(async_client, domain="ca", requested_location=" k1a0b1 ")
    assert first["geo_key"] == "K1A 0B1"
    duplicate = await async_client.post(
        "/api/products",
        json={
            "url": "https://www.amazon.ca/name/dp/b09xs7jwhh?ref=foo",
            "requested_location": "K1A 0B1",
        },
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["id"] == first["id"]
    different = await register(async_client, domain="ca", requested_location="M5V 3L9")
    assert different["id"] != first["id"]
    await async_client.delete(f"/api/products/{first['id']}")
    retracked = await register(async_client, domain="ca", requested_location="K1A0B1")
    assert retracked["id"] == first["id"] and retracked["is_tracked"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"asin": "bad"},
        {"asin": "B09XS7JWHH", "domain": "xyz"},
        {"asin": "B09XS7JWHH", "requested_location": "273015"},
        {"asin": "B09XS7JWHH", "domain": "in", "requested_location": "abc"},
        {"url": "https://amazon.com.evil.test/dp/B09XS7JWHH"},
        {"url": "file:///dp/B09XS7JWHH"},
        {"url": "https://amazon.com/s?k=headphones"},
        {"url": "https://user:secret@amazon.com/dp/B09XS7JWHH"},
        {"url": "https://amazon.com:bad/dp/B09XS7JWHH"},
        {"url": "https://amazon.in/dp/B09XS7JWHH", "domain": "com"},
        {"url": "https://amazon.com/dp/B09XS7JWHH", "asin": "B000000001"},
        {"url": "https://amazon.com/dp/B09XS7JWHH", "asin": None},
        {"url": "https://amazon.com/dp/B09XS7JWHH", "domain": 123},
        {"asin": "B09XS7JWHH", "is_tracked": False},
        {},
    ],
)
async def test_registration_invalid(async_client, db_session, payload):
    response = await async_client.post("/api/products", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"] == "invalid_input"
    assert await db_session.scalar(select(func.count(Product.id))) == 0


@pytest.mark.asyncio
async def test_list_detail_history_and_untrack_preserve_provenance(
    async_client, db_session, test_settings
):
    product = await register(async_client)
    later = await register(async_client, asin="B000000002")
    content = b"<html>Captured product</html>"
    path = test_settings.evidence_dir / "capture.html"
    path.write_bytes(content)
    artifact = EvidenceArtifact(
        evidence_type="html",
        storage_path=str(path),
        content_size_bytes=len(content),
        content_hash=hashlib.sha256(content).hexdigest(),
        source_url="https://www.amazon.com/dp/B09XS7JWHH",
        collector="playwright_amazon",
        captured_at=datetime.now(UTC),
    )
    db_session.add(artifact)
    await db_session.flush()
    first_time = datetime(2026, 10, 1, tzinfo=UTC)
    for offset, amount in ((0, "129.1234"), (1, "119.9999")):
        db_session.add(
            ProductObservation(
                product_id=product["id"],
                evidence_artifact_id=artifact.id,
                price_amount=Decimal(amount),
                currency="USD",
                source_url=artifact.source_url,
                captured_at=first_time + timedelta(days=offset),
                collector=artifact.collector,
                extraction_method="json_ld",
                evidence_id=artifact.content_hash,
            )
        )
    db_session.add(
        CompetitorRelationship(
            baseline_product_id=product["id"],
            competitor_product_id=later["id"],
            match_status="confirmed",
            match_score=0.9,
        )
    )
    await db_session.commit()
    detail = (await async_client.get(f"/api/products/{product['id']}")).json()
    assert detail["latest_observation"]["price_amount"] == "119.9999"
    assert detail["competitor_count"] == 1 and detail["last_collected_at"]
    assert detail["last_collected_at"].endswith("Z")
    candidates = (await async_client.get(f"/api/products/{product['id']}/competitors")).json()
    assert candidates[0]["competitor"]["asin"] == later["asin"]
    assert candidates[0]["competitor"]["latest_observation"] is None
    listing = await async_client.get("/api/products?page=2&limit=1")
    assert listing.json()["items"][0]["id"] == later["id"]
    assert listing.json()["total"] == 2
    history = await async_client.get(f"/api/products/{product['id']}/observations")
    assert len(history.json()) == 2
    for row in history.json():
        assert all(
            row[field]
            for field in (
                "source_url",
                "captured_at",
                "collector",
                "extraction_method",
                "evidence_id",
            )
        )
    filtered = await async_client.get(
        f"/api/products/{product['id']}/observations",
        params={"from": "2026-10-02T00:00:00Z", "to": "2026-10-02T00:00:00Z"},
    )
    assert len(filtered.json()) == 1
    response = await async_client.delete(f"/api/products/{product['id']}")
    assert response.status_code == 204 and response.content == b""
    assert (await async_client.get("/api/products")).json()["total"] == 1
    assert (await async_client.get("/api/products?tracked_only=false")).json()["total"] == 2
    assert len((await async_client.get(f"/api/products/{product['id']}/observations")).json()) == 2
    assert (await async_client.get(f"/api/evidence/{artifact.id}/content")).content == content
    # No observation mutation endpoints are exposed.
    assert (
        await async_client.post(f"/api/products/{product['id']}/observations", json={})
    ).status_code == 405


@pytest.mark.asyncio
async def test_empty_reads(async_client):
    assert (await async_client.get("/api/products")).json()["items"] == []
    assert (await async_client.get("/api/jobs")).json()["items"] == []
    product = await register(async_client)
    assert product["latest_observation"] is None
    assert (await async_client.get(f"/api/products/{product['id']}/observations")).json() == []
    assert (await async_client.get(f"/api/products/{product['id']}/competitors")).json() == []


@pytest.mark.asyncio
async def test_collection_enqueue_concurrent_dedup_terminal_requeue(async_client, db_session):
    product = await register(async_client)
    path = f"/api/products/{product['id']}/collect"
    responses = await asyncio.gather(
        *(async_client.post(path, json={"include_competitors": True}) for _ in range(5))
    )
    assert all(r.status_code == 202 for r in responses)
    job_id = responses[0].json()["id"]
    assert len({r.json()["id"] for r in responses}) == 1
    job = await db_session.get(CollectionJob, uuid.UUID(job_id))
    assert job.result == {"request": {"include_competitors": True}}
    assert job.status == "queued" and job.attempts == 0
    job.status = "succeeded"
    await db_session.commit()
    new_job = await async_client.post(path, json={"include_competitors": True})
    assert new_job.status_code == 202 and new_job.json()["id"] != job_id
    assert (await async_client.get(f"/api/jobs/{job_id}")).json()["status"] == "succeeded"
    queued = (await async_client.get("/api/jobs?status=queued&limit=1")).json()
    assert queued["total"] == 1 and len(queued["items"]) == 1


@pytest.mark.asyncio
async def test_cooldown_across_products_not_domains_expiry(async_client, db_session):
    source = await register(async_client)
    other = await register(async_client, asin="B000000002")
    canadian = await register(async_client, domain="ca")
    blocked = CollectionJob(
        kind="scrape_product",
        product_id=source["id"],
        request_key="old",
        status="failed",
        error_code="blocked",
        finished_at=datetime.now(UTC),
    )
    db_session.add(blocked)
    await db_session.commit()
    for suffix in ("collect", "competitors/scan"):
        response = await async_client.post(f"/api/products/{other['id']}/{suffix}")
        assert response.status_code == 429
        assert 0 < int(response.headers["Retry-After"]) <= 300
    assert (await async_client.post(f"/api/products/{canadian['id']}/collect")).status_code == 202
    blocked.finished_at = datetime.now(UTC) - timedelta(seconds=301)
    await db_session.commit()
    assert (await async_client.post(f"/api/products/{other['id']}/collect")).status_code == 202


@pytest.mark.asyncio
async def test_competitor_read_filters_and_scan_dedup(async_client, db_session):
    source = await register(async_client)
    for asin, score, status in (("B000000002", 0.9, "confirmed"), ("B000000003", 0.5, "ambiguous")):
        candidate = await register(async_client, asin=asin)
        db_session.add(
            CompetitorRelationship(
                baseline_product_id=source["id"],
                competitor_product_id=candidate["id"],
                match_score=score,
                match_status=status,
                evidence_summary={"title_similarity": score},
            )
        )
    await db_session.commit()
    path = f"/api/products/{source['id']}/competitors"
    rows = (await async_client.get(path, params={"status": "confirmed", "min_score": 0.8})).json()
    assert len(rows) == 1 and rows[0]["evidence_summary"]["title_similarity"] == 0.9
    first = await async_client.post(path + "/scan")
    second = await async_client.post(path + "/scan")
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["kind"] == "discover_competitors"


@pytest.mark.asyncio
async def test_evidence_metadata_bytes_and_failures(async_client, db_session, test_settings):
    data = b"<html><script>untrusted()</script>Original evidence</html>"
    path = test_settings.evidence_dir / "raw.html"
    path.write_bytes(data)
    artifact = EvidenceArtifact(
        evidence_type="html",
        storage_path="raw.html",
        content_size_bytes=len(data),
        content_hash=hashlib.sha256(data).hexdigest(),
        source_url="https://amazon.com/dp/B09XS7JWHH",
        collector="playwright_amazon",
        captured_at=datetime.now(UTC),
    )
    db_session.add(artifact)
    await db_session.commit()
    url = f"/api/evidence/{artifact.id}"
    metadata = await async_client.get(url)
    assert metadata.status_code == 200 and metadata.json()["content_hash"] == artifact.content_hash
    response = await async_client.get(url + "/content")
    assert response.status_code == 200 and response.content == data
    assert response.headers["content-disposition"] == "attachment"
    assert "sandbox" in response.headers["content-security-policy"]
    path.write_bytes(b"tampered")
    assert (await async_client.get(url + "/content")).status_code == 409
    path.unlink()
    assert (await async_client.get(url + "/content")).status_code == 404
    artifact.storage_path = "../outside.txt"
    await db_session.commit()
    assert (await async_client.get(url + "/content")).status_code == 409
    artifact.storage_path = "raw.html"
    artifact.evidence_type = "unknown"
    await db_session.commit()
    assert (await async_client.get(url + "/content")).status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("get", "/api/products/0", None),
        ("delete", "/api/products/bad", None),
        ("get", "/api/products?page=0", None),
        ("get", "/api/products?limit=101", None),
        ("get", "/api/products/1/observations?from=bad", None),
        ("get", "/api/products/1/observations?limit=0", None),
        (
            "get",
            "/api/products/1/observations?from=2026-10-03T00:00:00Z&to=2026-10-01T00:00:00Z",
            None,
        ),
        ("get", "/api/products/1/observations?from=2026-10-01", None),
        ("post", "/api/products/1/collect", {"include_competitors": "yes"}),
        ("post", "/api/products/1/collect", {"unexpected": 1}),
        ("post", "/api/products/0/competitors/scan", None),
        ("get", "/api/products/1/competitors?status=unknown", None),
        ("get", "/api/products/1/competitors?min_score=1.1", None),
        ("get", "/api/jobs?status=unknown", None),
        ("get", "/api/jobs?page=0", None),
        ("get", "/api/jobs/invalid", None),
        ("get", "/api/evidence/invalid", None),
        ("get", "/api/evidence/invalid/content", None),
    ],
)
async def test_endpoint_invalid_inputs(async_client, method, path, payload):
    response = await async_client.request(method, path, json=payload)
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/products/999"),
        ("delete", "/api/products/999"),
        ("get", "/api/products/999/observations"),
        ("post", "/api/products/999/collect"),
        ("get", "/api/products/999/competitors"),
        ("post", "/api/products/999/competitors/scan"),
        ("get", "/api/jobs/00000000-0000-0000-0000-000000000001"),
        ("get", "/api/evidence/00000000-0000-0000-0000-000000000001"),
        ("get", "/api/evidence/00000000-0000-0000-0000-000000000001/content"),
    ],
)
async def test_missing_resources(async_client, method, path):
    response = await async_client.request(method, path)
    assert response.status_code == 404 and response.json()["error"] == "not_found"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("post", "/api/products", {"asin": "B09XS7JWHH"}),
        ("get", "/api/products", None),
        ("get", "/api/products/1", None),
        ("delete", "/api/products/1", None),
        ("get", "/api/products/1/observations", None),
        ("post", "/api/products/1/collect", None),
        ("get", "/api/products/1/competitors", None),
        ("post", "/api/products/1/competitors/scan", None),
        ("get", "/api/jobs", None),
        ("get", "/api/jobs/00000000-0000-0000-0000-000000000001", None),
        ("get", "/api/evidence/00000000-0000-0000-0000-000000000001", None),
        ("get", "/api/evidence/00000000-0000-0000-0000-000000000001/content", None),
        ("post", "/api/products/1/analyze", None),
        ("get", "/api/analyses/00000000-0000-0000-0000-000000000001", None),
        ("get", "/api/analyses/00000000-0000-0000-0000-000000000001/claims", None),
        ("get", "/api/products/1/analytics", None),
        ("get", "/api/products/1/position", None),
        ("get", "/api/products/1/observations/export", None),
    ],
)
async def test_database_failures_sanitized(async_client, monkeypatch, method, path, payload):
    async def fail(*args, **kwargs):
        raise OperationalError("secret SQL", {"password": "secret"}, Exception("secret connection"))

    for operation in ("execute", "scalar", "scalars", "get"):
        monkeypatch.setattr(AsyncSession, operation, fail)
    response = await async_client.request(method, path, json=payload)
    assert response.status_code == 503
    assert response.json()["error"] == "database_unavailable"
    assert "secret" not in response.text


@pytest.mark.asyncio
async def test_failed_commit_rolls_back_registration(async_client, db_session, monkeypatch):
    async def fail_commit(*args, **kwargs):
        raise OperationalError("commit", {}, Exception("unavailable"))

    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "commit", fail_commit)
        response = await async_client.post("/api/products", json={"asin": "B09XS7JWHH"})
        assert response.status_code == 503
    assert await db_session.scalar(select(func.count(Product.id))) == 0
    assert (
        await async_client.post("/api/products", json={"asin": "B09XS7JWHH"})
    ).status_code == 201


@pytest.mark.asyncio
async def test_swagger_documents_completed_capabilities(async_client):
    assert (await async_client.get("/docs")).status_code == 200
    paths = (await async_client.get("/openapi.json")).json()["paths"]
    assert "/api/products/{product_id}/observations" in paths
    assert "/api/evidence/{evidence_id}/content" in paths
    assert "/api/products/{product_id}/analyze" in paths
    assert "/api/analyses/{run_id}" in paths
    assert "/api/products/{product_id}/analytics" in paths
    assert "/api/products/{product_id}/position" in paths


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["collect", "competitors/scan"])
async def test_failed_enqueue_commit_rolls_back(async_client, db_session, monkeypatch, suffix):
    product = await register(async_client)

    async def fail_commit(*args, **kwargs):
        raise OperationalError("commit", {}, Exception("unavailable"))

    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "commit", fail_commit)
        response = await async_client.post(f"/api/products/{product['id']}/{suffix}")
        assert response.status_code == 503
    assert await db_session.scalar(select(func.count(CollectionJob.id))) == 0


@pytest.mark.asyncio
async def test_integrity_failure_is_conflict(async_client, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    async def fail(*args, **kwargs):
        raise IntegrityError("secret constraint", {}, Exception("secret data"))

    monkeypatch.setattr(AsyncSession, "execute", fail)
    response = await async_client.post("/api/products", json={"asin": "B09XS7JWHH"})
    assert response.status_code == 409 and response.json()["error"] == "conflict"
    assert "secret" not in response.text


@pytest.mark.asyncio
async def test_evidence_read_os_error(async_client, db_session, monkeypatch):
    from pathlib import Path

    artifact = EvidenceArtifact(
        evidence_type="html",
        storage_path="raw.html",
        content_size_bytes=1,
        content_hash="a" * 64,
        source_url="https://amazon.com/dp/B09XS7JWHH",
        collector="playwright_amazon",
        captured_at=datetime.now(UTC),
    )
    db_session.add(artifact)
    await db_session.commit()

    def unreadable(*args, **kwargs):
        raise PermissionError("secret path")

    monkeypatch.setattr(Path, "read_bytes", unreadable)
    response = await async_client.get(f"/api/evidence/{artifact.id}/content")
    assert response.status_code == 503 and "secret" not in response.text
