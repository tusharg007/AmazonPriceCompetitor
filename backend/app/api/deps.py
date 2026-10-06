"""FastAPI dependency injection utilities."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import get_db_session


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
