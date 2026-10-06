"""Tests for FastAPI health check endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint_success(async_client: AsyncClient) -> None:
    response = await async_client.get("/api/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] in ("ok", "degraded")
    assert data["app_name"] == "Amazon Competitor Intelligence V2"
    assert data["app_version"] == "2.0.0"
    assert "database" in data
    assert data["database"]["status"] == "connected"
    assert "browser_environment" in data
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_root_health_alias(async_client: AsyncClient) -> None:
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "degraded")


@pytest.mark.asyncio
async def test_cors_no_wildcard_credentials(async_client: AsyncClient) -> None:
    """C-4: Verify that CORS does not return Access-Control-Allow-Origin: * with credentials."""
    response = await async_client.get(
        "/api/health",
        headers={"Origin": "http://localhost:5173"},
    )
    assert response.status_code == 200
    # The allowed origin should be echoed back exactly, never "*"
    acao = response.headers.get("access-control-allow-origin", "")
    assert acao != "*", "CORS must not use wildcard '*' — use explicit origin list"


@pytest.mark.asyncio
async def test_cors_rejects_unlisted_origin(async_client: AsyncClient) -> None:
    response = await async_client.options(
        "/api/health",
        headers={"Origin": "https://unlisted.example", "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
