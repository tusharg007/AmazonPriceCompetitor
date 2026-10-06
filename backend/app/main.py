"""FastAPI application entrypoint for Amazon Competitor Intelligence V2."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.api.deps import get_settings_dep
from app.api.health import router as health_router
from app.core.config import Settings, get_settings
from app.core.database import create_engine_and_session_factory
from app.models.base import Base

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifecycle managing database setup and teardown."""
    settings: Settings = app.state.settings
    logging.basicConfig(level=settings.log_level)
    logger.info(
        "Starting %s v%s in %s mode", settings.app_name, settings.app_version, settings.app_env
    )

    # A test may provide its own engine before entering the lifespan; its fixture owns disposal.
    external_engine: AsyncEngine | None = getattr(app.state, "engine", None)
    owns_engine = external_engine is None
    if external_engine is None:
        engine, session_factory = create_engine_and_session_factory(settings)
    else:
        engine = external_engine
        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    app.state.engine = engine
    app.state.session_factory = session_factory
    try:
        if settings.app_env in ("development", "testing"):
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                logger.info("Database schema initialized via create_all.")
        yield
    finally:
        logger.info("Shutting down %s...", settings.app_name)
        try:
            if owns_engine:
                cleanup = asyncio.create_task(engine.dispose())
                cancellation: asyncio.CancelledError | None = None
                while not cleanup.done():
                    try:
                        await asyncio.shield(cleanup)
                    except asyncio.CancelledError as exc:
                        cancellation = exc
                cleanup.result()
                if cancellation is not None:
                    raise cancellation
        finally:
            del app.state.engine
            del app.state.session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    """FastAPI application factory."""
    cfg = settings or get_settings()

    app = FastAPI(
        title=cfg.app_name,
        version=cfg.app_version,
        description="Production-grade Amazon Competitor Intelligence V2 API with evidence-backed provenance.",
        lifespan=lifespan,
    )
    app.state.settings = cfg

    # ------------------------------------------------------------------
    # C-4: CORS — never combine allow_origins=["*"] with allow_credentials=True.
    # Origins are configurable via APP_ALLOWED_ORIGINS (comma-separated) or
    # fall back to permissive localhost defaults for development.
    # ------------------------------------------------------------------
    allowed_origins = cfg.allowed_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,  # Set True only if using cookies / HTTP auth
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Global exception handler for unhandled ValueErrors
    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": "Validation Error", "detail": str(exc)},
        )

    # ------------------------------------------------------------------
    # M-3: Register health router once at /api prefix.
    # Expose a simple alias route at /health for load-balancer probes
    # without registering the same router twice (which pollutes OpenAPI).
    # ------------------------------------------------------------------
    app.include_router(health_router, prefix=cfg.api_prefix)

    @app.get("/health", include_in_schema=False)
    async def root_health_alias(
        request: Request, settings: Annotated[Settings, Depends(get_settings_dep)]
    ) -> JSONResponse:
        """Load-balancer-friendly alias — delegates to the canonical /api/health handler."""
        from app.api.health import get_health

        result = await get_health(request=request, settings=settings)
        return JSONResponse(content=result.model_dump(mode="json"))

    return app


app = create_app()
