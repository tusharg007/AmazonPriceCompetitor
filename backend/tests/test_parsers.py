"""Unit tests for pure parsing functions."""

from decimal import Decimal

from app.collector.parsers import (
    clean_text,
    normalized_query,
    parse_count,
    parse_decimal_price,
    parse_rating,
    product_asin_from_url,
)


def test_clean_text() -> None:
    assert clean_text(None) is None
    assert clean_text("") is None
    assert clean_text("   \xa0 Hello   World \n") == "Hello World"


def test_parse_decimal_price_multi_currency() -> None:
    # US Dollars
    amt, curr = parse_decimal_price("$1,299.99", "com")
    assert amt == Decimal("1299.99")
    assert curr == "USD"

    # German Euro format
    amt, curr = parse_decimal_price("1.299,99 €", "de")
    assert amt == Decimal("1299.99")
    assert curr == "EUR"

    # Indian Rupee
    amt, curr = parse_decimal_price("₹1,299", "in")
    assert amt == Decimal(1299)
    assert curr == "INR"

    # UAE Dirham
    amt, curr = parse_decimal_price("AED 50.00", "ae")
    assert amt == Decimal("50.00")
    assert curr == "AED"

    # Canadian Dollar
    amt, curr = parse_decimal_price("C$ 24.95", "ca")
    assert amt == Decimal("24.95")
    assert curr == "CAD"


def test_parse_rating() -> None:
    assert parse_rating(None) is None
    assert parse_rating("4.6 out of 5 stars") == 4.6
    assert parse_rating("4,7 von 5 Sternen") == 4.7
    assert parse_rating("5 out of 5") == 5.0
    assert parse_rating("invalid") is None


def test_parse_count() -> None:
    assert parse_count(None) is None
    assert parse_count("12,845 ratings") == 12845
    assert parse_count("1.234 Bewertungen") == 1234
    assert parse_count("5") == 5
    # H-4: K/M suffix expansion
    assert parse_count("12K ratings") == 12000
    assert parse_count("1.5K") == 1500
    assert parse_count("2M reviews") == 2_000_000
    assert parse_count("1.5M reviews") == 1_500_000
    assert parse_count("1,5K ratings") == 1_500
    assert parse_count("Rated by 2.5K customers") == 2_500
    assert parse_count("1,234 ratings (56 reviews)") == 1234


def test_price_locale_and_explicit_currency() -> None:
    assert parse_decimal_price("$24.95", "ca") == (Decimal("24.95"), "CAD")
    assert parse_decimal_price("1.299 €", "de") == (Decimal(1299), "EUR")
    assert parse_decimal_price("USD 24.95", "ca") == (Decimal("24.95"), "USD")
    assert parse_decimal_price("$24.95 CAD", "com") == (Decimal("24.95"), "CAD")


def test_product_asin_from_url() -> None:
    assert product_asin_from_url(None) is None
    assert product_asin_from_url("https://www.amazon.com/dp/B09XS7JWHH") == "B09XS7JWHH"
    assert (
        product_asin_from_url("https://www.amazon.in/gp/product/B0CX23VSAS/ref=xyz") == "B0CX23VSAS"
    )
    assert product_asin_from_url("https://www.google.com") is None


def test_normalized_query() -> None:
    title = "Sony WH-1000XM5 Noise Canceling Headphones - Over-Ear / Bluetooth Wireless"
    query = normalized_query(title)
    assert "Sony WH 1000XM5 Noise Canceling Headphones Over Ear Bluetooth Wireless" in query
    assert len(query) <= 180
