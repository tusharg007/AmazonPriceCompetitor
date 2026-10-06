"""Run the Phase 2 API against SQLite and optional isolated PostgreSQL, including races."""

import asyncio
import hashlib
import os
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from app.core.config import Settings
from app.core.database import create_engine_and_session_factory
from app.main import create_app
from app.models.base import Base
from app.models.entities import (
    CollectionJob,
    CompetitorRelationship,
    EvidenceArtifact,
    ProductObservation,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError


@pytest_asyncio.fixture(params=["sqlite", "postgresql"])
async def persistence(request, test_settings, tmp_path):
    if request.param == "postgresql":
        url = os.environ.get("ACI_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("Set ACI_TEST_POSTGRES_URL for actual PostgreSQL API verification")
        assert (make_url(url).database or "").endswith("_test")
        settings = Settings(
            app_env="testing",
            database_url=url,
            evidence_dir=tmp_path,
            api_rate_limit_per_minute=1000,
        )
    else:
        settings = test_settings
    engine, factory = create_engine_and_session_factory(settings)
    app = create_app(settings)
    app.state.engine = engine
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
        ):
            yield client, factory
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_product_and_job_upserts_both_databases(persistence):
    client, factory = persistence
    products = await asyncio.gather(
        *(client.post("/api/products", json={"asin": "B09XS7JWHH"}) for _ in range(6))
    )
    assert sorted(r.status_code for r in products) == [200] * 5 + [201]
    assert len({r.json()["id"] for r in products}) == 1
    product_id = products[0].json()["id"]
    requests = await asyncio.gather(
        *(client.post(f"/api/products/{product_id}/collect") for _ in range(6))
    )
    assert all(r.status_code == 202 for r in requests), [r.text for r in requests]
    assert len({r.json()["id"] for r in requests}) == 1
    async with factory() as session:
        row = (await session.scalars(select(CollectionJob))).one()
        values = {"product_id": product_id, "kind": row.kind, "request_key": row.request_key}
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                session.add(CollectionJob(**values, status="running"))
                await session.flush()
        # Terminal jobs do not occupy the partial index; repeated captures remain allowed.
        session.add(CollectionJob(**values, status="succeeded", finished_at=datetime.now(UTC)))
        await session.commit()
    detail = await client.get(f"/api/products/{product_id}")
    assert detail.status_code == 200
    assert (await client.get("/api/jobs")).json()["total"] == 2


@pytest.mark.asyncio
async def test_history_relationships_evidence_and_cooldown_both_databases(persistence, tmp_path):
    client, factory = persistence
    product = (await client.post("/api/products", json={"asin": "B09XS7JWHH"})).json()
    competitor = (await client.post("/api/products", json={"asin": "B000000002"})).json()
    # Use the app's configured directory for both database fixtures.
    root = client._transport.app.state.settings.evidence_dir
    raw = b"<html>Stored evidence</html>"
    (root / "stored.html").write_bytes(raw)
    captured = datetime(2026, 10, 6, tzinfo=UTC)
    async with factory() as session:
        evidence = EvidenceArtifact(
            evidence_type="html",
            storage_path="stored.html",
            content_size_bytes=len(raw),
            content_hash=hashlib.sha256(raw).hexdigest(),
            source_url="https://amazon.com/dp/B09XS7JWHH",
            collector="playwright_amazon",
            captured_at=captured,
        )
        session.add(evidence)
        await session.flush()
        session.add(
            ProductObservation(
                product_id=product["id"],
                evidence_artifact_id=evidence.id,
                source_url=evidence.source_url,
                captured_at=captured,
                collector=evidence.collector,
                extraction_method="json_ld",
                evidence_id=evidence.content_hash,
                price_amount=Decimal("10.4321"),
                currency="USD",
            )
        )
        session.add(
            CompetitorRelationship(
                baseline_product_id=product["id"],
                competitor_product_id=competitor["id"],
                match_status="confirmed",
                match_score=0.9,
            )
        )
        session.add(
            CollectionJob(
                product_id=product["id"],
                kind="scrape_product",
                request_key="blocked",
                status="failed",
                error_code="blocked",
                finished_at=datetime.now(UTC),
            )
        )
        await session.commit()
    detail = (await client.get(f"/api/products/{product['id']}")).json()
    assert (
        detail["latest_observation"]["price_amount"] == "10.4321"
        and detail["competitor_count"] == 1
    )
    history = await client.get(
        f"/api/products/{product['id']}/observations",
        params={"from": captured.isoformat(), "to": captured.isoformat()},
    )
    assert history.status_code == 200 and len(history.json()) == 1
    assert (
        await client.get(
            f"/api/products/{product['id']}/competitors?status=confirmed&min_score=0.8"
        )
    ).json()[0]["competitor_product_id"] == competitor["id"]
    assert (await client.get(f"/api/evidence/{evidence.id}/content")).content == raw
    assert (await client.post(f"/api/products/{competitor['id']}/collect")).status_code == 429
    assert (await client.delete(f"/api/products/{product['id']}")).status_code == 204
    assert len((await client.get(f"/api/products/{product['id']}/observations")).json()) == 1
    assert (await client.get(f"/api/evidence/{evidence.id}")).json()[
        "content_hash"
    ] == evidence.content_hash
