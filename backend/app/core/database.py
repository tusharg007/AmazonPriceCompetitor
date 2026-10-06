"""PostgreSQL-compatible async persistence layer using SQLAlchemy 2.0."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine_and_session_factory(
    settings: Settings | None = None,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create async SQLAlchemy engine and session factory based on settings."""
    cfg = settings or get_settings()
    url = cfg.database_url

    engine_kwargs: dict[str, Any] = {
        "echo": cfg.database_echo,
    }

    if url.startswith("sqlite"):
        database_path = make_url(url).database
        if database_path and database_path != ":memory:":
            Path(database_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # PostgreSQL pool settings
        engine_kwargs["pool_size"] = cfg.database_pool_size
        engine_kwargs["max_overflow"] = cfg.database_max_overflow

    engine = create_async_engine(url, **engine_kwargs)

    # Enable foreign keys and WAL for SQLite
    if url.startswith("sqlite"):

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    return engine, session_factory


@asynccontextmanager
async def get_db_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Dependency for obtaining an async database session per request.

    Uses the session factory owned by this FastAPI application.
    """
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


async def check_db_health(db_engine: AsyncEngine) -> dict[str, Any]:
    """Verify database connectivity and return basic metadata."""
    async with db_engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        scalar = result.scalar()
        dialect = db_engine.dialect.name
        return {
            "status": "connected" if scalar == 1 else "unhealthy",
            "dialect": dialect,
        }
