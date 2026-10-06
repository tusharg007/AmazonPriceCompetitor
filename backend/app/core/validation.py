"""Normalized Amazon identities and delivery context; no network access."""

import re
from urllib.parse import urlsplit

ASIN_REGEX = re.compile(r"^[A-Z0-9]{10}$")
SUPPORTED_DOMAINS = ("com", "in", "ca", "co.uk", "de", "fr", "it", "ae")


def normalize_asin(value: str) -> str:
    value = value.strip().upper()
    if not ASIN_REGEX.fullmatch(value):
        raise ValueError("Invalid ASIN. Must be 10 alphanumeric characters.")
    return value


def normalize_domain(value: str) -> str:
    value = value.strip().lower().removeprefix("amazon.")
    if value not in SUPPORTED_DOMAINS:
        raise ValueError(f"Unsupported domain. Supported: {SUPPORTED_DOMAINS}")
    return value


def amazon_identity(url: str) -> tuple[str, str]:
    # Collector exports load schemas; defer the existing parser to avoid a module cycle.
    from app.collector.parsers import product_asin_from_url

    parsed = urlsplit(url.strip())
    host = (parsed.hostname or "").lower()
    domain = host.removeprefix("www.").removeprefix("amazon.")
    if (
        parsed.scheme not in ("http", "https")
        or host not in (f"amazon.{domain}", f"www.amazon.{domain}")
        or domain not in SUPPORTED_DOMAINS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 80, 443)
    ):
        raise ValueError("URL must be a supported Amazon product URL")
    asin = product_asin_from_url(parsed.path)
    if asin is None:
        raise ValueError("URL must contain an Amazon /dp/ or /gp/product/ ASIN")
    return asin, domain


def normalize_location(domain: str, value: str | None) -> tuple[str, str | None]:
    # V1 geographic normalization and mismatch checks, extended with marketplace formats.
    value = " ".join((value or "").strip().upper().split())
    if not value:
        return "__default__", None
    if len(value) > 32:
        raise ValueError("Postal/delivery location must be 32 characters or fewer")
    patterns = {
        "com": r"\d{5}(?:-\d{4})?",
        "in": r"\d{6}",
        "ca": r"[A-Z]\d[A-Z] ?\d[A-Z]\d",
        "co.uk": r"(?:GIR ?0AA|[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2})",
        "de": r"\d{5}",
        "fr": r"\d{5}",
        "it": r"\d{5}",
    }
    if domain in patterns and not re.fullmatch(patterns[domain], value):
        raise ValueError(f"Invalid postal code format for amazon.{domain}")
    if domain in ("ca", "co.uk"):
        value = value.replace(" ", "")
        value = f"{value[:-3]} {value[-3:]}"
    # UAE uses a delivery locality rather than a national postal-code format.
    if domain == "ae" and not re.fullmatch(r"[^\x00-\x1f<>]{1,32}", value):
        raise ValueError("Invalid delivery locality")
    return value, value
