import json
from unittest.mock import Mock

import httpx
import pytest
from groq import BadRequestError
from langchain_core.runnables import RunnableLambda

from src.config import Settings
from src.db import DatabaseError
from src.llm import (
    LLMAnalysis,
    LLMCompetitorInsight,
    _bounded_analysis,
    _failed_generation,
    _normalize_analysis_payload,
    _schema_failure,
    run_analysis,
)


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


def _bad_request(body: dict[str, object]) -> BadRequestError:
    response = httpx.Response(400, request=httpx.Request("POST", "https://api.groq.com"))
    return BadRequestError(
        "Generated JSON does not match the expected schema", response=response, body=body
    )


def test_recover_schema_failure_with_scalar_recommendation() -> None:
    generated = {
        "summary": "A grounded summary",
        "positioning": "A grounded position",
        "top_competitors": [{"asin": "B0CX23VSAS", "key_points": "Price is lower"}],
        "recommendations": "Consider a price review",
    }
    error = _bad_request(
        {"error": {"code": "json_validate_failed", "failed_generation": json.dumps(generated)}}
    )
    assert _schema_failure(error)
    parsed = _failed_generation(error)
    assert parsed is not None
    assert _bounded_analysis(parsed, {"B0CX23VSAS"})["recommendations"] == [
        "Consider a price review"
    ]
    assert parsed.top_competitors[0].key_points == ["Price is lower"]


def test_incomplete_generation_requires_fallback() -> None:
    error = _bad_request(
        {"error": {"code": "json_validate_failed", "failed_generation": '{"summary":"cut off"'}}
    )
    assert _schema_failure(error)
    assert _failed_generation(error) is None


def test_recovery_rejects_malformed_analysis() -> None:
    with pytest.raises(ValueError, match="summary and positioning"):
        _normalize_analysis_payload({"summary": "", "positioning": "position"})
    with pytest.raises(ValueError):
        _normalize_analysis_payload(
            {"summary": "valid", "positioning": "valid", "recommendations": 5}
        )


@pytest.mark.parametrize("scenario", ["recover", "fallback", "invalid_fallback", "other_error"])
def test_analysis_provider_recovery(monkeypatch: pytest.MonkeyPatch, scenario: str) -> None:
    payload = {
        "summary": "Grounded summary",
        "positioning": "Grounded positioning",
        "recommendations": "Review the price",
        "top_competitors": [{"asin": "B0CX23VSAS", "key_points": ["Lower price"]}],
    }
    error = _bad_request(
        {
            "error": {
                "code": "invalid_api_key" if scenario == "other_error" else "json_validate_failed",
                "failed_generation": json.dumps(payload) if scenario == "recover" else "truncated",
            }
        }
    )

    def fail(_: object) -> None:
        raise error

    model = Mock()
    fallback = {**payload, "recommendations": 42} if scenario == "invalid_fallback" else payload
    model.with_structured_output.side_effect = [
        RunnableLambda(fail),
        RunnableLambda(lambda _: fallback),
    ]
    monkeypatch.setattr("langchain_groq.ChatGroq", Mock(return_value=model))
    monkeypatch.setattr(
        "src.llm.build_analysis_input",
        lambda *_: (
            41,
            7,
            {"competitors": [{"asin": "B0CX23VSAS"}]},
            "input-hash",
        ),
    )
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    settings = Mock(spec=Settings, groq_model="test-model")
    repo = Mock()
    if scenario in {"other_error", "invalid_fallback"}:
        with pytest.raises(DatabaseError) as caught:
            run_analysis(repo, 34, settings)
        assert "failed_generation" not in str(caught.value)
        assert "truncated" not in str(caught.value)
        repo.save_analysis.assert_not_called()
    else:
        output = run_analysis(repo, 34, settings)
        assert output["recommendations"] == ["Review the price"]
        repo.save_analysis.assert_called_once_with(41, 7, "input-hash", "test-model", output)
    assert model.with_structured_output.call_count == (
        2 if scenario in {"fallback", "invalid_fallback"} else 1
    )
