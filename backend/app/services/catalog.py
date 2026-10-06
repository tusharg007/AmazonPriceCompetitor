"""Product tracking, historical reads and verified evidence retrieval."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import InputError, NotFoundError
from app.core.validation import normalize_location
from app.models.entities import Product
from app.models.schemas import (
    CompetitorRead,
    EvidenceArtifactRead,
    Page,
    ProductCreate,
    ProductObservationRead,
    ProductRead,
    ProductResponse,
)
from app.repository import catalog
from app.services.evidence import read_verified_evidence


class CatalogService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def require_product(self, product_id: int) -> Product:
        product = await catalog.get_product(self.session, product_id)
        if product is None:
            raise NotFoundError("Product")
        return product

    async def responses(self, products: list[Product]) -> list[ProductResponse]:
        ids = [p.id for p in products]
        latest = await catalog.latest_observations(self.session, ids)
        counts = await catalog.competitor_counts(self.session, ids)
        return [
            ProductResponse(
                **ProductRead.model_validate(p).model_dump(),
                latest_observation=ProductObservationRead.model_validate(latest[p.id])
                if p.id in latest
                else None,
                competitor_count=counts.get(p.id, 0),
                last_collected_at=latest[p.id].captured_at if p.id in latest else None,
            )
            for p in products
        ]

    async def register(self, payload: ProductCreate) -> tuple[ProductResponse, bool]:
        geo_key, location = normalize_location(payload.domain, payload.requested_location)
        product, created = await catalog.get_or_create_product(
            self.session, payload.asin, payload.domain, geo_key, location
        )
        result = (await self.responses([product]))[0]
        # Commit before returning an HTTP success, including constraint failures.
        await self.session.commit()
        return result, created

    async def list_products(
        self, tracked_only: bool, page: int, limit: int
    ) -> Page[ProductResponse]:
        rows, total = await catalog.list_products(self.session, tracked_only, page, limit)
        return Page(items=await self.responses(rows), total=total, page=page, limit=limit)

    async def detail(self, product_id: int) -> ProductResponse:
        return (await self.responses([await self.require_product(product_id)]))[0]

    async def stop_tracking(self, product_id: int) -> None:
        await self.require_product(product_id)
        await catalog.untrack(self.session, product_id)
        await self.session.commit()

    async def history(
        self, product_id: int, start: datetime | None, end: datetime | None, limit: int
    ) -> list[ProductObservationRead]:
        # Require explicit offsets to avoid comparing naive and aware timestamps.
        for value in (start, end):
            if value is not None and value.tzinfo is None:
                raise InputError("History timestamps must include a timezone offset")
        start = start.astimezone(UTC) if start else None
        end = end.astimezone(UTC) if end else None
        if start and end and start > end:
            raise InputError("History 'from' must be before or equal to 'to'")
        await self.require_product(product_id)
        return [
            ProductObservationRead.model_validate(row)
            for row in await catalog.observations(self.session, product_id, start, end, limit)
        ]

    async def competitors(
        self, product_id: int, status: str | None, min_score: float
    ) -> list[CompetitorRead]:
        await self.require_product(product_id)
        rows = await catalog.competitors(self.session, product_id, status, min_score)
        details = {
            p.id: p
            for p in await self.responses(
                await catalog.get_products(
                    self.session, [row.competitor_product_id for row in rows]
                )
            )
        }
        return [
            CompetitorRead.model_validate(row).model_copy(
                update={"competitor": details.get(row.competitor_product_id)}
            )
            for row in rows
        ]

    async def evidence(self, evidence_id: UUID) -> EvidenceArtifactRead:
        row = await catalog.evidence(self.session, evidence_id)
        if row is None:
            raise NotFoundError("Evidence artifact")
        return EvidenceArtifactRead.model_validate(row)

    async def content(self, evidence_id: UUID) -> tuple[bytes, str]:
        artifact = await self.evidence(evidence_id)
        return await read_verified_evidence(self.settings, artifact)
