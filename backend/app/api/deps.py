"""FastAPI dependency injection utilities."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request, WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import get_db_session
from app.services.catalog import CatalogService
from app.services.jobs import JobProgressService, JobService


def collection_limit(request: Request) -> None:
    request.app.state.request_limiter.check(
        request.client.host if request.client else "unknown", "collection"
    )


def analysis_limit(request: Request) -> None:
    request.app.state.request_limiter.check(
        request.client.host if request.client else "unknown", "analysis"
    )


async def get_settings_dep(request: Request) -> Settings:
    """Dependency injecting application settings."""
    settings: Settings = request.app.state.settings
    return settings


async def get_db(
    request: Request,
) -> AsyncIterator[AsyncSession]:
    """Dependency injecting async SQLAlchemy database session.

    Reads ``request.app.state.session_factory`` so tests and production use the
    engine configured for this app's lifespan, never a module-level default.
    """
    async with get_db_session(request.app.state.session_factory) as session:
        yield session


def get_catalog_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> CatalogService:
    return CatalogService(session, settings)


def get_job_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> JobService:
    return JobService(session, settings)


def get_progress_service(websocket: WebSocket) -> JobProgressService:
    return JobProgressService(websocket.app.state.session_factory)
