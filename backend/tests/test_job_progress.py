"""Real ASGI WebSocket progress, terminal closure and disconnect/error behavior."""

import sqlite3
import uuid
from contextlib import closing

import pytest
from app.core.exceptions import ApplicationError
from app.main import create_app
from app.services.jobs import JobProgressService
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.websockets import WebSocketDisconnect


@pytest.fixture
def socket_client(test_settings):
    with TestClient(create_app(test_settings)) as client:
        yield client


def test_progress_queued_to_terminal(socket_client, test_settings):
    product = socket_client.post("/api/products", json={"asin": "B09XS7JWHH"}).json()
    job = socket_client.post(f"/api/products/{product['id']}/collect").json()
    with socket_client.websocket_connect(f"/ws/jobs/{job['id']}") as socket:
        assert socket.receive_json() == {
            "status": "queued",
            "progress": 0,
            "error_code": None,
            "error_message": None,
        }
        with (
            closing(
                sqlite3.connect(test_settings.database_url.removeprefix("sqlite+aiosqlite:///"))
            ) as db,
            db,
        ):
            db.execute(
                "UPDATE collection_jobs SET status='succeeded',progress=100 WHERE id=?",
                (uuid.UUID(job["id"]).hex,),
            )
        terminal = socket.receive_json()
        assert terminal["status"] == "succeeded" and terminal["progress"] == 100
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 1000


@pytest.mark.parametrize("identity", ["invalid", "00000000-0000-0000-0000-000000000001"])
def test_progress_invalid_missing(socket_client, identity):
    with socket_client.websocket_connect(f"/ws/jobs/{identity}") as socket:
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 1008


def test_progress_database_failure(socket_client, monkeypatch):
    async def fail(*args, **kwargs):
        raise ApplicationError("Database temporarily unavailable", "database_unavailable", 503)

    monkeypatch.setattr(JobProgressService, "read", fail)
    with socket_client.websocket_connect(f"/ws/jobs/{uuid.uuid4()}") as socket:
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 1011


def test_client_disconnect_does_not_hold_database(socket_client):
    product = socket_client.post("/api/products", json={"asin": "B09XS7JWHH"}).json()
    job = socket_client.post(f"/api/products/{product['id']}/collect").json()
    for _ in range(3):
        with socket_client.websocket_connect(f"/ws/jobs/{job['id']}") as socket:
            assert socket.receive_json()["status"] == "queued"
    assert socket_client.get(f"/api/jobs/{job['id']}").status_code == 200


@pytest.mark.asyncio
async def test_progress_service_releases_session_and_translates_db_error(
    async_client, test_engine, monkeypatch
):
    product = (await async_client.post("/api/products", json={"asin": "B09XS7JWHH"})).json()
    job = (await async_client.post(f"/api/products/{product['id']}/collect")).json()
    service = JobProgressService(async_sessionmaker(test_engine, expire_on_commit=False))
    assert (await service.read(uuid.UUID(job["id"]))).status == "queued"
    assert test_engine.pool.checkedout() == 0

    async def fail(*args, **kwargs):
        raise OperationalError("secret SQL", {}, Exception("secret"))

    monkeypatch.setattr(AsyncSession, "get", fail)
    with pytest.raises(ApplicationError) as error:
        await service.read(uuid.UUID(job["id"]))
    assert error.value.status_code == 503 and "secret" not in str(error.value)
    assert test_engine.pool.checkedout() == 0
