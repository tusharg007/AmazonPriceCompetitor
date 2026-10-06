"""Read-only append-only product history."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.api.products import Catalog, ProductID
from app.models.schemas import ProductObservationRead
from app.services.export import observations_csv

router = APIRouter(prefix="/products", tags=["observations"])


@router.get(
    "/{product_id}/observations/export",
    response_class=Response,
    description="CSV with exact captured values and provenance; maximum 10,000 captures per date range.",
)
async def export(
    product_id: ProductID,
    service: Catalog,
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
) -> Response:
    content = await observations_csv(service, product_id, start, end)
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="product-{product_id}-observations.csv"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{product_id}/observations", response_model=list[ProductObservationRead])
async def history(
    product_id: ProductID,
    service: Catalog,
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ProductObservationRead]:
    return await service.history(product_id, start, end, limit, offset)
