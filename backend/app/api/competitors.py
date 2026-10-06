"""Read auditable scored competitor relationships and enqueue discovery."""

from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.api.products import Catalog, Jobs, ProductID
from app.models.schemas import CollectionJobRead, CompetitorRead, MatchStatus

router = APIRouter(prefix="/products", tags=["competitors"])


@router.get("/{product_id}/competitors", response_model=list[CompetitorRead])
async def competitors(
    product_id: ProductID,
    service: Catalog,
    response: Response,
    status: MatchStatus | None = None,
    min_score: Annotated[float, Query(ge=0, le=1)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CompetitorRead]:
    rows = await service.competitors(product_id, status, min_score, limit, offset)
    response.headers["X-Total-Count"] = str(
        await service.competitor_total(product_id, status, min_score)
    )
    return rows


@router.post(
    "/{product_id}/competitors/scan",
    response_model=CollectionJobRead,
    status_code=202,
    description="Persist a discovery request; no browser work is performed in the API request.",
)
async def scan(product_id: ProductID, service: Jobs) -> CollectionJobRead:
    return await service.enqueue(product_id, "discover_competitors", True)
