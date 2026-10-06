"""Thin analysis request and citation reads; provider execution belongs to the worker."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_settings_dep
from app.api.products import ProductID
from app.core.config import Settings
from app.models.schemas import AnalysisClaimResponse, AnalysisResponse, CollectionJobRead
from app.services.analysis import AnalysisService

router = APIRouter(tags=["analysis"])


def get_analysis_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> AnalysisService:
    return AnalysisService(session, settings)


Service = Annotated[AnalysisService, Depends(get_analysis_service)]


@router.post("/products/{product_id}/analyze", response_model=CollectionJobRead, status_code=202)
async def analyze(product_id: ProductID, service: Service) -> CollectionJobRead:
    return await service.enqueue(product_id)


@router.get("/analyses/{run_id}", response_model=AnalysisResponse)
async def analysis_detail(run_id: UUID, service: Service) -> AnalysisResponse:
    return await service.detail(run_id)


@router.get("/analyses/{run_id}/claims", response_model=list[AnalysisClaimResponse])
async def analysis_claims(run_id: UUID, service: Service) -> list[AnalysisClaimResponse]:
    return (await service.detail(run_id)).claims
