"""Read-only append-only product history."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.products import Catalog, ProductID
from app.models.schemas import ProductObservationRead

router = APIRouter(prefix="/products", tags=["observations"])


@router.get("/{product_id}/observations", response_model=list[ProductObservationRead])
async def history(
    product_id: ProductID,
    service: Catalog,
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[ProductObservationRead]:
    return await service.history(product_id, start, end, limit)
