"""Decimal aggregation over UTC capture windows without interpolation or FX."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from app.models.entities import ProductObservation

Trend = Literal["rising", "falling", "stable", "insufficient_data"]


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def mean(values: list[Decimal]) -> Decimal | None:
    return (sum(values, Decimal(0)) / len(values)).quantize(Decimal("0.0001")) if values else None


def percent(current: Decimal | None, previous: Decimal | None) -> Decimal | None:
    if current is None or previous is None or previous == 0:
        return None
    return ((current - previous) / previous * 100).quantize(Decimal("0.0001"))


def usable(row: ProductObservation, currency: str | None) -> bool:
    return bool(
        currency
        and row.currency == currency
        and row.price_amount is not None
        and row.price_amount >= 0
        and row.location_status in ("default", "verified")
    )


def price_trend(
    rows: list[ProductObservation], currency: str | None, now: datetime
) -> tuple[Trend, Decimal | None, Decimal | None, Decimal | None]:
    recent, prior = [], []
    for row in rows:
        if not usable(row, currency) or row.price_amount is None:
            continue
        captured = utc(row.captured_at)
        if now - timedelta(days=7) <= captured <= now:
            recent.append(row.price_amount)
        elif now - timedelta(days=14) <= captured < now - timedelta(days=7):
            prior.append(row.price_amount)
    recent_mean, prior_mean = mean(recent), mean(prior)
    change = percent(recent_mean, prior_mean)
    trend: Trend = (
        "insufficient_data"
        if change is None
        else "rising"
        if change > 5
        else "falling"
        if change < -5
        else "stable"
    )
    return trend, recent_mean, prior_mean, change
