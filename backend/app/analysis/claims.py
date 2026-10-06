"""Deterministic numerical statements; AI prose is bounded and clearly interpretive."""

import re
from decimal import Decimal
from typing import Any

from app.analysis.errors import AnalysisError
from app.analysis.ported import LLMAnalysis, _bounded_analysis

PROMPT_VERSION = "v1-v2-numeric-boundary"
SCHEMA_VERSION = "v2-claims-1"


def numeric_comparable(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return bool(
        a.get("currency")
        and a["currency"] == b.get("currency")
        and a.get("price_amount") is not None
        and b.get("price_amount") is not None
        and a["domain"] == b["domain"]
        and a["geo_key"] == b["geo_key"]
        and a["location_status"] in ("default", "verified")
        and a["location_status"] == b["location_status"]
    )


def build_claims(
    parsed: LLMAnalysis, evidence: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    baseline = evidence["product"]
    competitors = {row["asin"]: row for row in evidence["competitors"]}
    output = _bounded_analysis(parsed, set(competitors))
    claims: list[dict[str, Any]] = []
    withheld = 0

    def add(
        kind: str,
        text: str,
        rows: list[dict[str, Any]],
        origin: str,
        value: dict[str, Any] | None = None,
    ) -> None:
        nonlocal withheld
        if origin == "llm_interpretation":
            # No model-supplied quantitative facts or arbitrary external URLs enter published claims.
            if re.search(
                r"[0-9$₹€£%]|https?://|\b(?:twice|double|half|percent|times cheaper)\b",
                text,
                re.IGNORECASE,
            ):
                withheld += 1
                return
            if not text.strip():
                return
        claims.append(
            {
                "claim_type": kind,
                "claim_text": text,
                "claim_value": {"origin": origin, **(value or {})},
                "sources": [
                    {
                        "observation_id": r["observation_id"],
                        "role": "baseline" if r is baseline else "competitor",
                    }
                    for r in rows
                ],
            }
        )

    cohort = [baseline, *competitors.values()]
    add("summary", output["summary"], cohort, "llm_interpretation")
    add("positioning", output["positioning"], cohort, "llm_interpretation")
    for insight in output["top_competitors"]:
        row = competitors[insight["asin"]]
        for point in insight["key_points"]:
            add("positioning", point, [baseline, row], "llm_interpretation", {"asin": row["asin"]})
    for recommendation in output["recommendations"]:
        add("recommendation", recommendation, cohort, "llm_interpretation")
    for row in competitors.values():
        if numeric_comparable(baseline, row):
            delta = Decimal(row["price_amount"]) - Decimal(baseline["price_amount"])
            add(
                "price_comparison",
                f"Captured competitor price {row['price_amount']} {row['currency']}; baseline {baseline['price_amount']} {baseline['currency']}; difference {delta:+f} {baseline['currency']}.",
                [baseline, row],
                "deterministic",
                {"asin": row["asin"], "difference": str(delta), "currency": baseline["currency"]},
            )
        if baseline.get("rating") is not None and row.get("rating") is not None:
            add(
                "rating_comparison",
                f"Captured listing ratings: baseline {baseline['rating']}/5 and competitor {row['rating']}/5. Ratings do not establish product quality.",
                [baseline, row],
                "deterministic",
                {"asin": row["asin"]},
            )
    if not any(c["claim_value"]["origin"] == "llm_interpretation" for c in claims):
        raise AnalysisError(
            "All generated prose failed the quantitative-output boundary. Retry analysis."
        )
    output["withheld_quantitative_claims"] = withheld
    return output, claims
