import pytest

from src.db import DatabaseError
from src.llm import LLMAnalysis, LLMCompetitorInsight, _bounded_analysis


def test_analysis_is_bounded_after_provider_schema_validation() -> None:
    parsed = LLMAnalysis(
        summary="s" * 1700,
        positioning="p" * 1700,
        top_competitors=[LLMCompetitorInsight(asin="B0CX23VSAS", key_points=["x" * 350] * 9)] * 12,
        recommendations=["r" * 350] * 10,
    )
    output = _bounded_analysis(parsed, {"B0CX23VSAS"})
    assert len(output["summary"]) == 1600
    assert len(output["positioning"]) == 1600
    assert len(output["top_competitors"]) == 10
    assert len(output["top_competitors"][0]["key_points"]) == 5
    assert len(output["top_competitors"][0]["key_points"][0]) == 300
    assert len(output["recommendations"]) == 8


def test_analysis_rejects_unsupported_asin() -> None:
    parsed = LLMAnalysis(
        summary="summary",
        positioning="positioning",
        top_competitors=[LLMCompetitorInsight(asin="UNSUPPORTED")],
    )
    with pytest.raises(DatabaseError, match="unsupported competitor ASINs"):
        _bounded_analysis(parsed, {"B0CX23VSAS"})
