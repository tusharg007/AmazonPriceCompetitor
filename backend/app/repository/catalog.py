"""Product identities and read-only observation/relationship/evidence queries."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    CompetitorRelationship,
    EvidenceArtifact,
    Product,
    ProductObservation,
)


async def get_product(session: AsyncSession, product_id: int) -> Product | None:
    return await session.get(Product, product_id)


async def get_products(session: AsyncSession, ids: list[int]) -> list[Product]:
    return list(await session.scalars(select(Product).where(Product.id.in_(ids))))


async def get_or_create_product(
    session: AsyncSession,
    asin: str,
    domain: str,
    geo_key: str,
    location: str | None,
    tracked: bool = True,
) -> tuple[Product, bool]:
    insert = pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    statement = (
        insert(Product)
        .values(
            asin=asin,
            domain=domain,
            geo_key=geo_key,
            requested_location=location,
            is_tracked=tracked,
        )
        .on_conflict_do_nothing(index_elements=["asin", "domain", "geo_key"])
        .returning(Product.id)
    )
    created = (await session.execute(statement)).scalar_one_or_none() is not None
    product = (
        await session.scalars(
            select(Product).where(
                Product.asin == asin,
                Product.domain == domain,
                Product.geo_key == geo_key,
            )
        )
    ).one()
    if tracked and not product.is_tracked:
        product.is_tracked = True
        await session.flush()
    return product, created


async def list_products(
    session: AsyncSession, tracked_only: bool, page: int, limit: int
) -> tuple[list[Product], int]:
    statement = select(Product)
    if tracked_only:
        statement = statement.where(Product.is_tracked.is_(True))
    total = (await session.scalar(select(func.count()).select_from(statement.subquery()))) or 0
    rows = await session.scalars(
        statement.order_by(Product.id).offset((page - 1) * limit).limit(limit)
    )
    return list(rows), total


async def untrack(session: AsyncSession, product_id: int) -> None:
    # Never delete Product or cascade into its historical evidence.
    await session.execute(update(Product).where(Product.id == product_id).values(is_tracked=False))


async def latest_observations(
    session: AsyncSession, ids: list[int], as_of: datetime | None = None
) -> dict[int, ProductObservation]:
    query = select(
        ProductObservation.id,
        func.row_number()
        .over(
            partition_by=ProductObservation.product_id,
            order_by=(ProductObservation.captured_at.desc(), ProductObservation.id.desc()),
        )
        .label("rank"),
    ).where(ProductObservation.product_id.in_(ids))
    if as_of is not None:
        query = query.where(ProductObservation.captured_at <= as_of)
    ranked = query.subquery()
    rows = await session.scalars(
        select(ProductObservation)
        .join(ranked, ranked.c.id == ProductObservation.id)
        .where(ranked.c.rank == 1)
    )
    return {row.product_id: row for row in rows}


async def competitor_counts(session: AsyncSession, ids: list[int]) -> dict[int, int]:
    rows = await session.execute(
        select(CompetitorRelationship.baseline_product_id, func.count())
        .where(
            CompetitorRelationship.baseline_product_id.in_(ids),
            CompetitorRelationship.match_status == "confirmed",
        )
        .group_by(CompetitorRelationship.baseline_product_id)
    )
    return dict(rows.tuples().all())


async def observations(
    session: AsyncSession,
    product_id: int,
    start: datetime | None,
    end: datetime | None,
    limit: int,
    offset: int = 0,
) -> list[ProductObservation]:
    query = select(ProductObservation).where(ProductObservation.product_id == product_id)
    if start is not None:
        query = query.where(ProductObservation.captured_at >= start)
    if end is not None:
        query = query.where(ProductObservation.captured_at <= end)
    return list(
        await session.scalars(
            query.order_by(ProductObservation.captured_at, ProductObservation.id)
            .offset(offset)
            .limit(limit)
        )
    )


async def competitors(
    session: AsyncSession,
    product_id: int,
    status: str | None,
    min_score: float,
    limit: int | None = None,
    offset: int = 0,
) -> list[CompetitorRelationship]:
    query = select(CompetitorRelationship).where(
        CompetitorRelationship.baseline_product_id == product_id,
        CompetitorRelationship.match_score >= min_score,
    )
    if status is not None:
        query = query.where(CompetitorRelationship.match_status == status)
    query = query.order_by(
        CompetitorRelationship.match_score.desc(), CompetitorRelationship.id
    ).offset(offset)
    if limit is not None:
        query = query.limit(limit)
    return list(await session.scalars(query))


async def competitor_total(
    session: AsyncSession, product_id: int, status: str | None, min_score: float
) -> int:
    query = select(func.count(CompetitorRelationship.id)).where(
        CompetitorRelationship.baseline_product_id == product_id,
        CompetitorRelationship.match_score >= min_score,
    )
    if status is not None:
        query = query.where(CompetitorRelationship.match_status == status)
    return (await session.scalar(query)) or 0


async def evidence(session: AsyncSession, evidence_id: UUID) -> EvidenceArtifact | None:
    return await session.get(EvidenceArtifact, evidence_id)
