"""Product tracking and durable collection request endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response

from app.api.deps import collection_limit, get_catalog_service, get_job_service
from app.models.schemas import (
    CollectionJobRead,
    CollectRequest,
    Page,
    ProductCreate,
    ProductResponse,
)
from app.services.catalog import CatalogService
from app.services.jobs import JobService

router = APIRouter(prefix="/products", tags=["products"])
Catalog = Annotated[CatalogService, Depends(get_catalog_service)]
Jobs = Annotated[JobService, Depends(get_job_service)]
ProductID = Annotated[int, Path(gt=0)]


@router.post(
    "",
    response_model=ProductResponse,
    status_code=201,
    responses={
        200: {"model": ProductResponse, "description": "Existing identity registered again"}
    },
)
async def create_product(
    payload: ProductCreate, response: Response, service: Catalog
) -> ProductResponse:
    result, created = await service.register(payload)
    response.status_code = 201 if created else 200
    return result


@router.get("", response_model=Page[ProductResponse])
async def list_products(
    service: Catalog,
    tracked_only: bool = True,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[ProductResponse]:
    return await service.list_products(tracked_only, page, limit)


@router.get("/{product_id}", response_model=ProductResponse)
async def product_detail(product_id: ProductID, service: Catalog) -> ProductResponse:
    return await service.detail(product_id)


@router.delete("/{product_id}", status_code=204)
async def stop_tracking(product_id: ProductID, service: Catalog) -> Response:
    await service.stop_tracking(product_id)
    return Response(status_code=204)


@router.post(
    "/{product_id}/collect",
    response_model=CollectionJobRead,
    status_code=202,
    description="Persist a collection request for the standalone Playwright worker.",
    dependencies=[Depends(collection_limit)],
)
async def collect(
    product_id: ProductID, service: Jobs, payload: CollectRequest | None = None
) -> CollectionJobRead:
    return await service.enqueue(
        product_id, "scrape_product", payload.include_competitors if payload else False
    )
