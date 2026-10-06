"""The approved five-factor score, conservative structured conflicts and audit inputs."""

import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.matching.exclusions import _brand, select_comparable_competitors

POLICY_VERSION = "deterministic-v1"
WEIGHTS = {
    "title_similarity": 0.35,
    "brand_score": 0.25,
    "category_overlap": 0.20,
    "price_proximity": 0.15,
    "rating_proximity": 0.05,
}
STOP_WORDS = {"the", "a", "an", "and", "with", "for", "of", "by", "in", "to", "new"}


def text(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def tokens(value: Any, brand: Any = None) -> set[str]:
    return (
        set(re.findall(r"\w+", text(value))) - STOP_WORDS - set(re.findall(r"\w+", _brand(brand)))
    )


def positive(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value))
        return number if number.is_finite() and number > 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def normalized_attributes(row: dict[str, Any]) -> dict[str, str]:
    """Normalize supplied structured attributes; never guess absent specifications."""
    attributes = dict(row.get("attributes") or {})
    raw = row.get("raw_metadata") or {}
    attributes.update(raw.get("attributes") or {})
    structured = raw.get("json_ld") or {}
    properties = structured.get("additionalProperty", []) if isinstance(structured, dict) else []
    properties = [properties] if isinstance(properties, dict) else properties
    for entry in properties if isinstance(properties, list) else []:
        if isinstance(entry, dict) and entry.get("name") and entry.get("value") is not None:
            attributes[text(entry["name"]).replace(" ", "_")] = entry["value"]
    aliases = {
        "quantity": "pack_size",
        "number_of_items": "pack_size",
        "item_count": "pack_size",
        "size": "dimensions",
        "product_type": "product_type",
        "model_name": "model",
    }
    result = {
        aliases.get(text(k).replace(" ", "_"), text(k).replace(" ", "_")): text(v)
        for k, v in attributes.items()
        if v is not None and text(v)
    }
    if row.get("variant"):
        result["variant"] = text(row["variant"])
    if "dimensions" in result:
        result["dimensions"] = result["dimensions"].replace(" ", "").replace("×", "x")
    # This reads extracted title text, not page HTML. Only explicit pack claims are used.
    pack = re.search(r"\b(?:pack of (\d+)|(\d+)[ -]?pack)\b", text(row.get("title")))
    if pack and "pack_size" not in result:
        result["pack_size"] = pack.group(1) or pack.group(2)
    for key in ("pack_size", "capacity"):
        value = result.get(key, "")
        measure = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(ml|l|g|kg)?", value)
        if measure:
            number = Decimal(measure.group(1))
            unit = measure.group(2) or ""
            if unit in ("l", "kg"):
                number *= 1000
                unit = "ml" if unit == "l" else "g"
            result[key] = f"{number.normalize():f}{unit}"
    return result


def classify_match(score: float) -> str:
    return "confirmed" if score >= 0.7 else "ambiguous" if score >= 0.3 else "rejected"


@dataclass(frozen=True)
class MatchDecision:
    score: float
    status: str
    reason: str | None
    evidence: dict[str, Any]


def evaluate_match(baseline: dict[str, Any], candidate: dict[str, Any]) -> MatchDecision:
    attributes_a, attributes_b = normalized_attributes(baseline), normalized_attributes(candidate)
    evidence: dict[str, Any] = {
        "policy_version": POLICY_VERSION,
        "weights": WEIGHTS,
        "baseline": {
            "title": baseline.get("title"),
            "brand": _brand(baseline.get("brand")),
            "attributes": attributes_a,
        },
        "candidate": {
            "title": candidate.get("title"),
            "brand": _brand(candidate.get("brand")),
            "attributes": attributes_b,
        },
    }
    for name, row in (("baseline", baseline), ("candidate", candidate)):
        evidence[name].update(
            price_amount=str(row["price_amount"]) if row.get("price_amount") is not None else None,
            currency=row.get("currency"),
            categories=row.get("categories", []),
            rating=row.get("rating"),
        )
    reason = None
    if baseline.get("domain") != candidate.get("domain") or baseline.get(
        "geo_key"
    ) != candidate.get("geo_key"):
        reason = "marketplace_or_location_mismatch"
    elif baseline.get("asin") == candidate.get("asin"):
        reason = "same_product"
    elif candidate.get("sponsored"):
        reason = "sponsored_listing"
    else:
        _, excluded = select_comparable_competitors(baseline, [candidate])
        if excluded:
            reason = next(iter(excluded)).replace(" ", "_")
    for key in ("product_type", "pack_size", "capacity", "dimensions", "variant"):
        if (
            reason is None
            and key in attributes_a
            and key in attributes_b
            and attributes_a[key] != attributes_b[key]
        ):
            reason = f"{key}_mismatch"
    if reason:
        evidence["exclusion_reasons"] = {reason: 1}
        return MatchDecision(0.0, "rejected", reason, evidence)
    a, b = (
        tokens(baseline.get("title"), baseline.get("brand")),
        tokens(candidate.get("title"), candidate.get("brand")),
    )
    brand_a, brand_b = _brand(baseline.get("brand")), _brand(candidate.get("brand"))
    cats_a, cats_b = (
        {text(c) for c in baseline.get("categories", [])},
        {text(c) for c in candidate.get("categories", [])},
    )
    price_a, price_b = (
        positive(baseline.get("price_amount")),
        positive(candidate.get("price_amount")),
    )
    rating_a, rating_b = baseline.get("rating"), candidate.get("rating")
    parts = {
        "title_similarity": len(a & b) / len(a | b) if a | b else 0.0,
        "brand_score": 0.5 if not brand_a or not brand_b else float(brand_a == brand_b),
        "category_overlap": len(cats_a & cats_b) / max(len(cats_a), len(cats_b))
        if cats_a or cats_b
        else 0.0,
        "price_proximity": max(0.0, 1.0 - abs(math.log(float(price_a / price_b))) / math.log(2))
        if price_a and price_b
        else 0.0,
        "rating_proximity": max(0.0, 1.0 - abs(float(rating_a) - float(rating_b)) / 5)
        if rating_a is not None and rating_b is not None
        else 0.5,
    }
    score = round(sum(WEIGHTS[key] * value for key, value in parts.items()), 8)
    status = classify_match(score)
    evidence.update(parts)
    evidence["missing_attributes"] = sorted(set(attributes_a) ^ set(attributes_b))
    evidence["exclusion_reasons"] = {}
    return MatchDecision(
        score, status, "low_match_score" if status == "rejected" else None, evidence
    )
