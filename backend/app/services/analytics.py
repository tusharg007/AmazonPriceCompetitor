"""Historical stats and confirmed-cohort positions computed from stored observations."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import median

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.prices import mean, percent, price_trend, usable, utc
from app.core.config import Settings
from app.models.schemas import CompetitivePosition, DailyPrice, PositionEntry, PriceAnalytics
from app.repository import analytics, catalog
from app.services.catalog import CatalogService


class AnalyticsService:
    def __init__(
        self, session: AsyncSession, settings: Settings, now: datetime | None = None
    ) -> None:
        self.session, self.settings, self.now = session, settings, now or datetime.now(UTC)

    async def prices(
        self, product_id: int, window_days: int, currency: str | None = None
    ) -> PriceAnalytics:
        await CatalogService(self.session, self.settings).require_product(product_id)
        rows = (
            await analytics.window(
                self.session,
                [product_id],
                self.now - timedelta(days=max(14, window_days)),
                self.now,
            )
        ).get(product_id, [])
        selected = currency or (rows[-1].currency if rows else None)
        window_rows = [
            r for r in rows if utc(r.captured_at) >= self.now - timedelta(days=window_days)
        ]
        priced = [r for r in window_rows if usable(r, selected)]
        values = [r.price_amount for r in priced if r.price_amount is not None]
        daily: dict[str, list] = {}
        for row in priced:
            daily.setdefault(utc(row.captured_at).date().isoformat(), []).append(row)
        current = (
            window_rows[-1].price_amount
            if window_rows and usable(window_rows[-1], selected)
            else None
        )
        previous = (
            window_rows[-2].price_amount
            if len(window_rows) > 1 and usable(window_rows[-2], selected)
            else None
        )
        trend, recent, prior, trend_change = price_trend(rows, selected, self.now)
        return PriceAnalytics(
            product_id=product_id,
            currency=selected,
            window_days=window_days,
            as_of=self.now,
            observation_count=len(window_rows),
            priced_count=len(values),
            minimum=min(values) if values else None,
            maximum=max(values) if values else None,
            average=mean(values),
            current=current,
            previous=previous,
            change=current - previous if current is not None and previous is not None else None,
            change_percent=percent(current, previous),
            recent_average=recent,
            prior_average=prior,
            trend_change_percent=trend_change,
            trend=trend,
            daily=[
                DailyPrice(
                    day=day,
                    average=mean([r.price_amount for r in captures]),
                    count=len(captures),
                    observation_ids=[r.id for r in captures],
                )
                for day, captures in daily.items()
            ],
        )

    async def position(self, product_id: int) -> CompetitivePosition:
        baseline = await CatalogService(self.session, self.settings).require_product(product_id)
        matches = await catalog.competitors(self.session, product_id, "confirmed", 0)
        products = {
            p.id: p
            for p in await catalog.get_products(
                self.session, [product_id, *[m.competitor_product_id for m in matches]]
            )
        }
        latest = await catalog.latest_observations(self.session, list(products), self.now)
        parent = latest.get(product_id)
        currency = parent.currency if parent else None
        entries = []
        for identity, p in products.items():
            row = latest.get(identity)
            if (
                parent is None
                or not usable(parent, currency)
                or row is None
                or not usable(row, currency)
                or p.domain != baseline.domain
                or p.geo_key != baseline.geo_key
                or row.location_status != parent.location_status
            ):
                continue
            assert row.price_amount is not None and currency is not None
            entries.append(
                PositionEntry(
                    product_id=p.id,
                    asin=p.asin,
                    title=row.raw_metadata.get("_listing", {}).get("title", p.title),
                    baseline=p.id == product_id,
                    price_amount=row.price_amount,
                    currency=currency,
                    captured_at=row.captured_at,
                    observation_id=row.id,
                    evidence_artifact_id=row.evidence_artifact_id,
                )
            )
        entries.sort(key=lambda e: (e.price_amount, e.product_id))
        sufficient = len(entries) > 1 and parent is not None and parent.price_amount is not None
        baseline_price = parent.price_amount if parent else None
        rank = (
            1 + sum(e.price_amount < baseline_price for e in entries)
            if sufficient and baseline_price is not None
            else None
        )
        return CompetitivePosition(
            product_id=product_id,
            currency=currency,
            price_rank=rank,
            price_percentile=Decimal(rank - 1) / Decimal(len(entries) - 1) if rank else None,
            total_in_set=len(entries),
            median=median([e.price_amount for e in entries]) if sufficient else None,
            excluded_count=len(products) - len(entries),
            reason=None if sufficient else "Insufficient comparable current prices",
            entries=entries,
        )
