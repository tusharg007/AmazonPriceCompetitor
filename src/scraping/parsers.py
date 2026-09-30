"""Pure page-text parsing. These functions are unit-testable without a browser."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

CURRENCY_BY_DOMAIN = {
    "com": "USD",
    "ca": "CAD",
    "co.uk": "GBP",
    "de": "EUR",
    "fr": "EUR",
    "it": "EUR",
    "ae": "AED",
}
SYMBOL_TO_CURRENCY = {"£": "GBP", "€": "EUR", "AED": "AED", "د.إ": "AED", "C$": "CAD", "CA$": "CAD"}


def clean_text(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = " ".join(value.replace("\xa0", " ").split()).strip()
    return cleaned or None


def parse_decimal_price(text: str | None, domain: str) -> tuple[Decimal | None, str | None]:
    value = clean_text(text)
    if not value:
        return None, None
    currency = next((code for symbol, code in SYMBOL_TO_CURRENCY.items() if symbol in value), None)
    currency = currency or CURRENCY_BY_DOMAIN.get(domain)
    number = re.search(r"(?:\d{1,3}(?:[ .,'’]\d{3})*|\d+)(?:[,.]\d{2})?", value)
    if not number:
        return None, currency
    raw = number.group(0).replace(" ", "").replace("'", "").replace("’", "")
    if raw.count(",") and raw.count("."):
        normalized = (
            raw.replace(".", "").replace(",", ".")
            if raw.rfind(",") > raw.rfind(".")
            else raw.replace(",", "")
        )
    elif "," in raw:
        normalized = (
            raw.replace(".", "").replace(",", ".")
            if len(raw.rsplit(",", 1)[-1]) == 2
            else raw.replace(",", "")
        )
    else:
        normalized = raw.replace(",", "")
    try:
        amount = Decimal(normalized)
    except InvalidOperation:
        return None, currency
    return (amount, currency) if amount >= 0 else (None, currency)


def parse_rating(text: str | None) -> float | None:
    value = clean_text(text)
    if not value:
        return None
    match = re.search(r"([0-5](?:[,.]\d+)?)", value)
    if not match:
        return None
    rating = float(match.group(1).replace(",", "."))
    return rating if 0 <= rating <= 5 else None


def parse_count(text: str | None) -> int | None:
    value = clean_text(text)
    if not value:
        return None
    digits = re.sub(r"[^0-9]", "", value)
    return int(digits) if digits else None


def product_asin_from_url(url: str) -> str | None:
    match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?]|$)", url.upper())
    return match.group(1) if match else None


def normalized_query(title: str) -> str:
    value = clean_text(title) or ""
    return value[:180]
