"""Thin deterministic analytics routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_settings_dep
from app.api.products import ProductID
from app.core.config import Settings
from app.models.schemas import CompetitivePosition, PriceAnalytics
from app.services.analytics import AnalyticsService

router = APIRouter(prefix="/products", tags=["analytics"])


def get_analytics_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> AnalyticsService:
    return AnalyticsService(session, settings)


Service = Annotated[AnalyticsService, Depends(get_analytics_service)]


@router.get("/{product_id}/analytics", response_model=PriceAnalytics)
async def prices(
    product_id: ProductID,
    service: Service,
    window_days: Annotated[int, Query(ge=1, le=3650)] = 30,
    currency: Annotated[str | None, Query(pattern="^[A-Z]{3}$")] = None,
) -> PriceAnalytics:
    return await service.prices(product_id, window_days, currency)


@router.get("/{product_id}/position", response_model=CompetitivePosition)
async def position(product_id: ProductID, service: Service) -> CompetitivePosition:
    return await service.position(product_id)
