"""Job status HTTP and WebSocket transports."""

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from app.api.deps import get_progress_service
from app.api.products import Jobs
from app.core.exceptions import ApplicationError
from app.models.schemas import CollectionJobRead, JobStatus, Page
from app.services.jobs import JobProgressService

router = APIRouter(tags=["jobs"])
socket_router = APIRouter()


@router.get("/jobs", response_model=Page[CollectionJobRead])
async def jobs(
    service: Jobs,
    status: JobStatus | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[CollectionJobRead]:
    return await service.list(status, page, limit)


@router.get("/jobs/{job_id}", response_model=CollectionJobRead)
async def detail(job_id: UUID, service: Jobs) -> CollectionJobRead:
    return await service.detail(job_id)


@socket_router.websocket("/ws/jobs/{job_id}")
async def progress(
    websocket: WebSocket,
    job_id: str,
    service: Annotated[JobProgressService, Depends(get_progress_service)],
) -> None:
    await websocket.accept()
    try:
        try:
            identity = UUID(job_id)
        except ValueError:
            await websocket.close(code=1008, reason="Invalid job UUID")
            return
        while True:
            snapshot = await service.read(identity)
            await websocket.send_json(snapshot.model_dump(mode="json"))
            if snapshot.status not in ("queued", "running"):
                await websocket.close(code=1000)
                return
            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=1.5)
                if message["type"] == "websocket.disconnect":
                    return
                # Client messages do not speed up polling or mutate job state.
                await asyncio.sleep(1.5)
            except TimeoutError:
                pass
    except WebSocketDisconnect:
        return
    except ApplicationError as exc:
        await websocket.close(code=1008 if exc.status_code == 404 else 1011, reason=str(exc))
