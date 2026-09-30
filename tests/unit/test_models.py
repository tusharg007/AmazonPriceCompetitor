from decimal import Decimal

import pytest

from src.models import ProductKey, ValidationError, normalize_geo
from src.scraping.parsers import parse_decimal_price, parse_rating


def test_product_key_normalizes_identity() -> None:
    assert ProductKey(" b0cx23vsas ", "amazon.co.uk") == ProductKey("B0CX23VSAS", "co.uk")


@pytest.mark.parametrize("value", ["", "B0CX23VS", "B0CX23VSASX", "invalid-asin"])
def test_invalid_asin_is_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        ProductKey(value, "com")


def test_geo_preserves_leading_zeroes() -> None:
    assert normalize_geo("001 23") == ("001 23", "001 23")


@pytest.mark.parametrize(
    ("text", "domain", "amount", "currency"),
    [
        ("$1,299.99", "com", Decimal("1299.99"), "USD"),
        ("1.299,99 €", "de", Decimal("1299.99"), "EUR"),
        ("AED 1,299.99", "ae", Decimal("1299.99"), "AED"),
        ("C$ 24.95", "ca", Decimal("24.95"), "CAD"),
    ],
)
def test_price_parsing_is_locale_aware(
    text: str, domain: str, amount: Decimal, currency: str
) -> None:
    assert parse_decimal_price(text, domain) == (amount, currency)


def test_rating_parser_handles_comma_separator() -> None:
    assert parse_rating("4,7 out of 5 stars") == 4.7
