"""Batch history reads for price analytics and dashboard trends."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ProductObservation


async def window(
    session: AsyncSession, ids: list[int], start: datetime, end: datetime
) -> dict[int, list[ProductObservation]]:
    rows = await session.scalars(
        select(ProductObservation)
        .where(
            ProductObservation.product_id.in_(ids),
            ProductObservation.captured_at >= start,
            ProductObservation.captured_at <= end,
        )
        .order_by(ProductObservation.captured_at, ProductObservation.id)
    )
    grouped: dict[int, list[ProductObservation]] = {}
    for row in rows:
        grouped.setdefault(row.product_id, []).append(row)
    return grouped
