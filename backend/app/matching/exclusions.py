"""Conservative, auditable selection of like-for-like price comparisons."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any


def _brand(value: Any) -> str:
    brand = str(value or "").strip().casefold()
    brand = re.sub(r"^visit the\s+", "", brand)
    brand = re.sub(r"^brand:\s*", "", brand)
    brand = re.sub(r"\s+store$", "", brand)
    return brand.strip()


def select_comparable_competitors(
    parent: dict[str, Any], competitors: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Keep plausible same-market, same-price-tier listings; preserve exclusion counts."""
    included: list[dict[str, Any]] = []
    excluded: dict[str, int] = {}
    parent_brand = _brand(parent.get("brand"))
    parent_price = parent.get("price_amount")
    for row in competitors:
        title = str(row.get("title") or "").casefold()
        row_brand = _brand(row.get("brand"))
        reason: str | None = None
        if not title:
            reason = "missing title"
        elif any(
            phrase in title
            for phrase in ("cad version", "latin american version", "international version")
        ):
            reason = "different market version"
        elif parent_brand and (
            f"for {parent_brand}" in title or f"compatible with {parent_brand}" in title
        ):
            reason = "compatibility listing"
        elif parent_brand and row_brand and row_brand != parent_brand and parent_brand in title:
            reason = "title and brand disagree"
        elif row.get("price_amount") is None:
            reason = "price unavailable"
        elif not parent.get("currency") or not row.get("currency"):
            reason = "currency unavailable"
        elif parent.get("currency") != row.get("currency"):
            reason = "currency mismatch"
        elif parent.get("requested_location") and (
            parent.get("location_status") != "verified" or row.get("location_status") != "verified"
        ):
            reason = "delivery location unverified"
        elif parent_price is not None and Decimal(parent_price) > 0:
            ratio = Decimal(row["price_amount"]) / Decimal(parent_price)
            if ratio < Decimal("0.50") or ratio > Decimal("2.00"):
                reason = "outside comparable price band"
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        included.append(
            row | {"price_comparable": parent_price is not None and Decimal(parent_price) > 0}
        )
    return included, excluded
