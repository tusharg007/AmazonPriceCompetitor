"""Request budgets, bounded evidence, and frozen provenance failures."""

from collections import deque
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from app.analysis.claims import build_claims
from app.analysis.errors import AnalysisError
from app.analysis.ported import LLMAnalysis
from app.collector.amazon import AmazonCollector
from app.collector.errors import ScrapingError
from app.core.config import Settings
from app.core.exceptions import RateLimitError
from app.core.rate_limit import RequestLimiter
from app.main import create_app
from httpx import ASGITransport, AsyncClient

from backend.tests.test_analysis import seed


def test_documented_environment_selects_production_without_double_prefix(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_APP_ENV", "development")
    settings = Settings(_env_file=None, evidence_dir=tmp_path)
    assert settings.app_env == "production"
    monkeypatch.delenv("APP_ENV")
    assert Settings(_env_file=None, evidence_dir=tmp_path).app_env == "development"


def test_sliding_limit_expiration_scope_clients_and_capacity():
    now = [100.0]
    limiter = RequestLimiter(5, lambda: now[0])
    for _ in range(5):
        limiter.check("one", "collection")
    with pytest.raises(RateLimitError) as error:
        limiter.check("one", "collection")
    assert error.value.retry_after == 60
    limiter.check("one", "analysis")
    limiter.check("two", "collection")
    now[0] += 60
    limiter.check("one", "collection")
    assert len(limiter.windows) == 1
    limiter.windows = {(str(i), "collection"): deque([now[0]]) for i in range(4096)}
    with pytest.raises(RateLimitError):
        limiter.check("new", "collection")


@pytest.mark.asyncio
async def test_api_budget_shared_collection_independent_analysis(test_settings, test_engine):
    test_settings.api_rate_limit_per_minute = 5
    app = create_app(test_settings)
    app.state.engine = test_engine
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        product = (await client.post("/api/products", json={"asin": "B000000001"})).json()
        for _ in range(5):
            assert (await client.post(f"/api/products/{product['id']}/collect")).status_code == 202
        limited = await client.post(f"/api/products/{product['id']}/competitors/scan")
        assert limited.status_code == 429 and limited.json()["error"] == "rate_limited"
        assert int(limited.headers["Retry-After"]) > 0
        assert (await client.post(f"/api/products/{product['id']}/analyze")).status_code == 409
        assert (await client.get("/api/products")).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["source_url", "collector", "captured_at"])
async def test_analysis_rejects_mismatched_artifact_metadata(
    async_client, db_session, test_settings, field
):
    products, observations = await seed(db_session, test_settings)
    observation = observations[0]
    setattr(
        observation,
        field,
        observation.captured_at + timedelta(seconds=1) if field == "captured_at" else "incorrect",
    )
    await db_session.commit()
    response = await async_client.post(f"/api/products/{products[0].id}/analyze")
    assert response.status_code == 409 and "inconsistent" in response.json()["detail"]


@pytest.mark.asyncio
async def test_evidence_read_bound_checks_metadata_and_actual_file(
    async_client, db_session, test_settings
):
    from app.models.entities import EvidenceArtifact

    _, observations = await seed(db_session, test_settings)
    artifact = await db_session.get(EvidenceArtifact, observations[0].evidence_artifact_id)
    test_settings.max_evidence_bytes = 10
    response = await async_client.get(f"/api/evidence/{artifact.id}/content")
    assert response.status_code == 413
    artifact.content_size_bytes = 1
    await db_session.commit()
    response = await async_client.get(f"/api/evidence/{artifact.id}/content")
    assert response.status_code == 413  # File size cannot evade the cap via stale metadata.


@pytest.mark.asyncio
async def test_analysis_payload_bound(async_client, db_session, test_settings):
    products, _ = await seed(db_session, test_settings)
    test_settings.max_analysis_input_bytes = 1
    response = await async_client.post(f"/api/products/{products[0].id}/analyze")
    assert response.status_code == 413 and response.json()["error"] == "input_too_large"


@pytest.mark.asyncio
async def test_capture_size_guard_publishes_no_file(test_settings):
    test_settings.max_evidence_bytes = 10
    collector = AmazonCollector(test_settings)
    page = AsyncMock()
    page.content.return_value = "a" * 11
    with pytest.raises(ScrapingError, match="size limit"):
        await collector.capture_evidence(page, "test")
    assert not list(test_settings.evidence_dir.iterdir())


def test_invalid_model_asin_is_sanitized():
    parsed = LLMAnalysis(
        summary="summary",
        positioning="position",
        top_competitors=[{"asin": "secret arbitrary provider data"}],
    )
    with pytest.raises(AnalysisError) as error:
        build_claims(parsed, {"product": {}, "competitors": []})
    assert "secret" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exception,status", [(ValueError("secret value"), 422), (RuntimeError("secret path"), 500)]
)
async def test_unexpected_api_errors_are_sanitized(test_settings, exception, status):
    from app.api.deps import get_catalog_service

    app = create_app(test_settings)

    def broken():
        raise exception

    app.dependency_overrides[get_catalog_service] = broken
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        response = await client.get("/api/products")
    assert response.status_code == status and "secret" not in response.text
