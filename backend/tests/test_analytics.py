"""Decimal history, bounded cohort ranks, CSV safety and API error contracts."""

import csv
import io
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.analytics.prices import percent, price_trend
from app.models.entities import CompetitorRelationship, Product, ProductObservation
from app.services.analytics import AnalyticsService
from app.services.export import csv_cell
from sqlalchemy import update

from backend.tests.test_analysis import seed


@pytest.mark.asyncio
async def test_history_analytics_decimal_windows_and_currency(
    db_session, test_settings, async_client
):
    products, observations = await seed(db_session, test_settings)
    now = datetime.now(UTC)
    for days, price, currency, status in [
        (2, "120.1234", "USD", "default"),
        (9, "80.0000", "USD", "default"),
        (10, "9999", "INR", "default"),
        (11, "9999", "USD", "unverified"),
    ]:
        db_session.add(
            ProductObservation(
                product_id=products[0].id,
                price_amount=Decimal(price),
                currency=currency,
                location_status=status,
                source_url=observations[0].source_url,
                captured_at=now - timedelta(days=days),
                collector="fixture",
                extraction_method="json_ld",
                evidence_id=observations[0].evidence_id,
            )
        )
    await db_session.commit()
    result = await AnalyticsService(db_session, test_settings, now).prices(products[0].id, 30)
    assert result.observation_count == 5 and result.priced_count == 3
    assert result.minimum == Decimal("80.0000") and result.maximum == Decimal("120.1234")
    assert result.average == Decimal("100.0411") and result.trend == "rising"
    assert result.current == Decimal(100) and result.previous == Decimal("120.1234")
    assert result.change == Decimal("-20.1234")
    assert len(result.daily) == 3 and all(d.observation_ids for d in result.daily)
    response = await async_client.get(f"/api/products/{products[0].id}/analytics")
    assert response.status_code == 200 and response.json()["minimum"] == "80.0000"
    cards = (await async_client.get("/api/products")).json()["items"]
    assert cards[0]["price_trend"] == "rising"
    one_day = await AnalyticsService(db_session, test_settings, now).prices(products[0].id, 1)
    assert one_day.priced_count == 1 and one_day.change is None


@pytest.mark.asyncio
async def test_competitive_position_ties_missing_and_other_currency(
    db_session, test_settings, async_client
):
    products, observations = await seed(db_session, test_settings)
    result = await AnalyticsService(db_session, test_settings).position(products[0].id)
    assert result.price_rank == 1 and result.price_percentile == 0
    assert result.total_in_set == 2 and result.median == Decimal(105)
    assert {e.observation_id for e in result.entries} == {o.id for o in observations}
    third = Product(asin="B000000003", domain="in", is_tracked=False)
    db_session.add(third)
    await db_session.flush()
    db_session.add(
        CompetitorRelationship(
            baseline_product_id=products[0].id,
            competitor_product_id=third.id,
            match_status="confirmed",
            match_score=0.8,
        )
    )
    db_session.add(
        ProductObservation(
            product_id=third.id,
            price_amount=Decimal(1),
            currency="INR",
            source_url="https://www.amazon.in/dp/B000000003",
            captured_at=datetime.now(UTC),
            collector="fixture",
            extraction_method="json_ld",
            evidence_id="a" * 64,
        )
    )
    db_session.add(
        ProductObservation(
            product_id=products[1].id,
            price_amount=Decimal(100),
            currency="USD",
            source_url=observations[1].source_url,
            captured_at=datetime.now(UTC),
            collector="fixture",
            extraction_method="json_ld",
            evidence_id="b" * 64,
        )
    )
    await db_session.commit()
    tied = (await async_client.get(f"/api/products/{products[0].id}/position")).json()
    assert tied["price_rank"] == 1 and tied["price_percentile"] == "0"
    assert tied["total_in_set"] == 2 and tied["excluded_count"] == 1
    await db_session.execute(update(CompetitorRelationship).values(match_status="rejected"))
    await db_session.commit()
    insufficient = await AnalyticsService(db_session, test_settings).position(products[0].id)
    assert insufficient.price_rank is None and insufficient.median is None and insufficient.reason


@pytest.mark.asyncio
async def test_no_history_and_missing_price_are_not_zero(async_client, db_session, test_settings):
    product = (await async_client.post("/api/products", json={"asin": "B000000001"})).json()
    empty = (await async_client.get(f"/api/products/{product['id']}/analytics")).json()
    assert (
        empty["current"] is None
        and empty["average"] is None
        and empty["trend"] == "insufficient_data"
    )
    db_session.add(
        ProductObservation(
            product_id=product["id"],
            currency="USD",
            source_url="https://www.amazon.com/dp/B000000001",
            captured_at=datetime.now(UTC),
            collector="fixture",
            extraction_method="structured_dom",
            evidence_id="a" * 64,
        )
    )
    await db_session.commit()
    result = await AnalyticsService(db_session, test_settings).prices(product["id"], 30)
    assert result.observation_count == 1 and result.priced_count == 0 and result.current is None


@pytest.mark.asyncio
async def test_csv_export_provenance_formula_safety_and_pagination(
    async_client, db_session, test_settings
):
    products, observations = await seed(db_session, test_settings)
    response = await async_client.get(f"/api/products/{products[0].id}/observations/export")
    assert response.status_code == 200 and "attachment" in response.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows[0]["observation_id"] == str(observations[0].id)
    assert rows[0]["price_amount"] == "100.0000" and rows[0]["captured_at"].endswith("Z")
    assert rows[0]["evidence_id"] == observations[0].evidence_id
    assert (
        await async_client.get(f"/api/products/{products[0].id}/observations?limit=1&offset=1")
    ).json() == []
    page = await async_client.get(f"/api/products/{products[0].id}/competitors?limit=1&offset=1")
    assert page.json() == [] and page.headers["x-total-count"] == "1"
    assert csv_cell('  =HYPERLINK("evil")').startswith("'")
    assert csv_cell("+CMD") == "'+CMD" and csv_cell("100.0000") == "100.0000"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,status",
    [
        ("/api/products/999/analytics", 404),
        ("/api/products/999/position", 404),
        ("/api/products/999/observations/export", 404),
        ("/api/products/bad/analytics", 422),
        ("/api/products/1/analytics?window_days=0", 422),
        ("/api/products/1/analytics?currency=usd", 422),
        ("/api/products/1/observations/export?from=bad", 422),
        ("/api/products/1/competitors?offset=-1", 422),
        ("/api/products/1/observations?offset=-1", 422),
    ],
)
async def test_analytics_invalid_and_not_found(async_client, path, status):
    assert (await async_client.get(path)).status_code == status


@pytest.mark.parametrize(
    "recent,prior,expected",
    [
        ("110", "100", "rising"),
        ("90", "100", "falling"),
        ("105", "100", "stable"),
        ("10", "0", "insufficient_data"),
    ],
)
def test_trend_thresholds_and_zero_denominator(recent, prior, expected):
    now = datetime.now(UTC)
    rows = [
        ProductObservation(
            price_amount=Decimal(recent),
            currency="USD",
            location_status="default",
            captured_at=now - timedelta(days=1),
        ),
        ProductObservation(
            price_amount=Decimal(prior),
            currency="USD",
            location_status="default",
            captured_at=now - timedelta(days=8),
        ),
    ]
    assert price_trend(rows, "USD", now)[0] == expected
    assert percent(Decimal(1), Decimal(0)) is None
