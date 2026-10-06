"""Pure string and numerical parsing functions for Amazon page attributes."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

CURRENCY_BY_DOMAIN: dict[str, str] = {
    "com": "USD",
    "in": "INR",
    "ca": "CAD",
    "co.uk": "GBP",
    "de": "EUR",
    "fr": "EUR",
    "it": "EUR",
    "ae": "AED",
}

SYMBOL_TO_CURRENCY: dict[str, str] = {
    "$": "USD",
    "£": "GBP",
    "€": "EUR",
    "₹": "INR",
    "AED": "AED",
    "د.إ": "AED",
    "C$": "CAD",
    "CA$": "CAD",
}

ASIN_URL_PATTERN = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?]|$)", re.IGNORECASE)
PRICE_PATTERN = re.compile(
    r"(?P<symbol>C\$|CA\$|CAD|AED|EUR|USD|GBP|INR|د\.إ|[$£€₹])?\s*(?P<amount>\d[\d., ]*\d|\d)\s*(?P<suffix>CAD|AED|د\.إ|EUR|USD|GBP|INR)?",
    re.IGNORECASE,
)
RATING_PATTERN = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:out of 5 stars|von 5 Sternen|sur 5 étoiles|su 5 stelle|de 5 estrellas)?",
    re.IGNORECASE,
)
COUNT_PATTERN = re.compile(r"[\d,.]+")


def clean_text(value: str | None) -> str | None:
    """Normalize whitespace and strip control / non-breaking space characters."""
    if not value:
        return None
    normalized = " ".join(value.replace("\xa0", " ").strip().split())
    return normalized or None


def parse_decimal_price(text: str | None, domain: str) -> tuple[Decimal | None, str | None]:
    """Parse locale-aware price string and extract numeric Decimal and ISO currency code."""
    cleaned = clean_text(text)
    if not cleaned:
        return None, None

    match = PRICE_PATTERN.search(cleaned)
    if not match:
        return None, None

    symbol = match.group("symbol")
    suffix = match.group("suffix")
    raw_amount = match.group("amount").replace(" ", "")

    currency = None
    if symbol:
        currency = SYMBOL_TO_CURRENCY.get(symbol.upper(), SYMBOL_TO_CURRENCY.get(symbol))
        if not currency and symbol.upper() in CURRENCY_BY_DOMAIN.values():
            currency = symbol.upper()
        if symbol == "$" and domain == "ca":
            currency = "CAD"
    if suffix:
        currency = SYMBOL_TO_CURRENCY.get(suffix.upper(), suffix.upper())
    if not currency:
        currency = CURRENCY_BY_DOMAIN.get(domain)

    # Decimal normalization handling US vs European comma/dot formats
    if "," in raw_amount and "." in raw_amount:
        if raw_amount.rfind(",") > raw_amount.rfind("."):
            # German/French: 1.299,99
            raw_amount = raw_amount.replace(".", "").replace(",", ".")
        else:
            # US/UK: 1,299.99
            raw_amount = raw_amount.replace(",", "")
    elif "," in raw_amount:
        # e.g., "1299,99" or "1,299"
        parts = raw_amount.split(",")
        if len(parts[-1]) == 2:
            raw_amount = raw_amount.replace(",", ".")
        else:
            raw_amount = raw_amount.replace(",", "")
    elif (
        "." in raw_amount
        and domain in ("de", "fr", "it")
        and len(raw_amount.rsplit(".", 1)[-1]) == 3
    ):
        raw_amount = raw_amount.replace(".", "")

    try:
        amount = Decimal(raw_amount)
        if amount.is_finite() and amount >= 0:
            return amount, currency
    except InvalidOperation:
        pass

    return None, currency


def parse_rating(text: str | None) -> float | None:
    """Extract floating-point rating value between 0.0 and 5.0."""
    cleaned = clean_text(text)
    if not cleaned:
        return None
    match = RATING_PATTERN.search(cleaned)
    if not match:
        return None
    raw = match.group(1).replace(",", ".")
    try:
        val = float(raw)
        if 0.0 <= val <= 5.0:
            return round(val, 2)
    except ValueError:
        pass
    return None


def parse_count(text: str | None) -> int | None:
    """Extract integer count (e.g. review count) from text.

    Handles K/M suffixes (e.g. "12K ratings" → 12000, "1.5M" → 1500000).
    """
    cleaned = clean_text(text)
    if not cleaned:
        return None

    # H-4: Expand K / M suffixes before stripping non-digits
    km_match = re.search(r"\b([\d,.]+)\s*([km])\b", cleaned.lower())
    if km_match:
        multipliers = {"k": 1_000, "m": 1_000_000}
        base_str = km_match.group(1)
        if "," in base_str and "." in base_str:
            if base_str.rfind(",") > base_str.rfind("."):
                base_str = base_str.replace(".", "").replace(",", ".")
            else:
                base_str = base_str.replace(",", "")
        elif "," in base_str:
            if len(base_str.rsplit(",", 1)[-1]) in (1, 2):
                base_str = base_str.replace(",", ".")
            else:
                base_str = base_str.replace(",", "")
        try:
            return int(Decimal(base_str) * multipliers[km_match.group(2)])
        except (InvalidOperation, ValueError, KeyError):
            pass

    match = COUNT_PATTERN.search(cleaned)
    digits = re.sub(r"[^\d]", "", match.group()) if match else ""
    if digits:
        try:
            return int(digits)
        except ValueError:
            pass
    return None


def product_asin_from_url(url: str | None) -> str | None:
    """Extract 10-character Amazon ASIN from URL."""
    if not url:
        return None
    match = ASIN_URL_PATTERN.search(url)
    return match.group(1).upper() if match else None


def normalized_query(title: str, max_chars: int = 180) -> str:
    """Derive clean, truncated search query from a product title."""
    cleaned = clean_text(title) or ""
    # Strip typical noise words
    cleaned = re.sub(r"[|,/\-–—]+", " ", cleaned)
    tokens = [t for t in cleaned.split() if len(t) > 1]
    query = " ".join(tokens)
    return query[:max_chars].strip()
