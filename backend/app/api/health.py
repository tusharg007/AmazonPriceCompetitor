"""Health check and readiness API endpoints."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import get_settings_dep
from app.core.config import Settings
from app.core.database import check_db_health
from app.models.schemas import HealthCheckResponse

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthCheckResponse,
    status_code=status.HTTP_200_OK,
    summary="Application Health and Readiness Status",
)
async def get_health(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> HealthCheckResponse:
    """Check database connectivity and browser environment readiness."""
    # C-3: Use the engine stored in app.state by lifespan, not a module-level singleton.
    engine = request.app.state.engine
    db_status = await check_db_health(engine)

    # Check browser runtime readiness
    browsers_path = settings.playwright_browsers_path or os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    chromium_found = False
    if browsers_path:
        b_path = Path(browsers_path)
        if b_path.exists() and any("chromium" in p.name.lower() for p in b_path.iterdir()):
            chromium_found = True

    browser_env = {
        "headless": settings.playwright_headless,
        "browsers_path": str(browsers_path) if browsers_path else None,
        "chromium_installed": chromium_found,
        "evidence_dir_ready": settings.evidence_dir.exists(),
    }

    return HealthCheckResponse(
        status="ok" if db_status.get("status") == "connected" else "degraded",
        app_name=settings.app_name,
        app_version=settings.app_version,
        database=db_status,
        browser_environment=browser_env,
        timestamp=datetime.now(UTC),
    )
