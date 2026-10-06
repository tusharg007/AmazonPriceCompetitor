"""The Groq boundary is mocked; no keys or external requests are used."""

import ast
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from app.analysis.errors import AnalysisError
from app.analysis.ported import PROMPT, LLMAnalysis, _failed_generation
from app.analysis.provider import GroqProvider, reasoning_input
from groq import APIStatusError, BadRequestError
from langchain_core.runnables import RunnableLambda


def payload():
    return {
        "summary": "Filtered cohort.",
        "positioning": "Similar listing claims.",
        "recommendations": "Verify source evidence.",
        "top_competitors": [],
    }


def schema_error(generated=None):
    return BadRequestError(
        "schema failed",
        response=httpx.Response(400, request=httpx.Request("POST", "https://api.groq.com")),
        body={"error": {"code": "json_validate_failed", "failed_generation": generated}},
    )


def test_verbatim_port_parity():
    source = ast.parse(Path("src/llm.py").read_text(encoding="utf-8"))
    target = ast.parse(Path("backend/app/analysis/ported.py").read_text(encoding="utf-8"))
    names = {
        "LLMAnalysis",
        "LLMCompetitorInsight",
        "_normalize_analysis_payload",
        "_schema_failure",
        "_failed_generation",
        "_bounded_analysis",
    }
    original = {
        node.name: ast.dump(node, include_attributes=False)
        for node in source.body
        if getattr(node, "name", None) in names
    }
    copied = {
        node.name: ast.dump(node, include_attributes=False)
        for node in target.body
        if getattr(node, "name", None) in names
    }
    assert original == copied
    call = next(
        node
        for node in ast.walk(source)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "PromptTemplate"
    )
    assert (
        ast.literal_eval(next(item.value for item in call.keywords if item.arg == "template"))
        == PROMPT
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["strict", "recovered", "fallback", "failure"])
async def test_provider_schema_tiers(monkeypatch, test_settings, mode):
    test_settings.groq_api_key = "test-only"
    methods = []

    class Model:
        def with_structured_output(self, *args, method, **kwargs):
            methods.append(method)

            def response(_):
                import json

                if mode == "failure":
                    raise RuntimeError("secret provider response")
                if method == "json_schema" and mode in ("recovered", "fallback"):
                    raise schema_error(json.dumps(payload()) if mode == "recovered" else "{broken")
                return payload()

            return RunnableLambda(response)

    monkeypatch.setattr("app.analysis.provider.ChatGroq", lambda **kwargs: Model())
    if mode == "failure":
        with pytest.raises(AnalysisError) as exc:
            await GroqProvider(test_settings).generate({"product": {}})
        assert "secret" not in str(exc.value)
    else:
        result = await GroqProvider(test_settings).generate({"product": {}})
        assert isinstance(result, LLMAnalysis) and result.recommendations == [
            "Verify source evidence."
        ]
        assert methods == (["json_schema", "json_mode"] if mode == "fallback" else ["json_schema"])


def test_failed_generation_invalid_and_oversize():
    assert _failed_generation(schema_error("{" + "x" * 100000)) is None
    assert _failed_generation(schema_error("[]")) is None


def test_reasoning_input_preserves_cohort_and_facts_without_mutating_provenance():
    row = {
        "asin": "B000000001",
        "title": "Actual listing",
        "price_amount": "649",
        "currency": "INR",
        "price_comparable": False,
        "source_url": "https://www.amazon.in/dp/B000000001",
        "evidence_id": "a" * 64,
        "observation_id": "exact-capture",
        "collector": "playwright_amazon",
        "category_path": ["Shoes"],
    }
    evidence = {
        "product": row,
        "competitors": [dict(row, asin=f"B{i:09d}") for i in range(20)],
        "rules": {"cohort": "saved matches"},
    }
    original = deepcopy(evidence)
    compact = reasoning_input(evidence)
    assert evidence == original
    assert len(compact["competitors"]) == 20
    assert compact["rules"] == evidence["rules"]
    assert compact["product"]["price_amount"] == "649"
    assert compact["product"]["category_path"] == ["Shoes"]
    assert compact["competitors"][0]["price_comparable"] is False
    assert "source_url" not in compact["product"]
    assert "evidence_id" not in compact["product"]
    assert len(json.dumps(compact)) < len(json.dumps(evidence))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status, message",
    [(413, "token limit"), (429, "rate limit"), (401, "authentication"), (503, "unavailable")],
)
async def test_provider_actionable_status_and_bounded_request(
    monkeypatch, test_settings, status, message
):
    test_settings.groq_api_key = "test-only"
    options = {}

    def model(**kwargs):
        options.update(kwargs)

        class Model:
            def with_structured_output(self, *args, **kwargs):
                def respond(prompt):
                    assert "private-artifact-hash" not in prompt.to_string()
                    assert prompt.messages[0].type == "system"
                    assert "Every prose string must omit digits" in prompt.messages[0].content
                    raise APIStatusError(
                        "private provider response",
                        response=httpx.Response(
                            status, request=httpx.Request("POST", "https://api.groq.com")
                        ),
                        body={"secret": "provider-details"},
                    )

                return RunnableLambda(respond)

        return Model()

    monkeypatch.setattr("app.analysis.provider.ChatGroq", model)
    with pytest.raises(AnalysisError, match=message) as error:
        await GroqProvider(test_settings).generate(
            {"product": {"asin": "B000000001", "evidence_id": "private-artifact-hash"}}
        )
    assert "private" not in str(error.value)
    assert options["max_tokens"] == 2048
    assert options["reasoning_effort"] == "low"


@pytest.mark.asyncio
async def test_provider_real_model_options_and_constructor_errors(monkeypatch, test_settings):
    from langchain_groq import ChatGroq

    # Validate against the installed integration without making an API request.
    model = ChatGroq(
        model="openai/gpt-oss-20b",
        api_key="test-placeholder",
        max_tokens=2048,
        reasoning_effort="low",
    )
    assert model.max_tokens == 2048 and model.reasoning_effort == "low"
    test_settings.groq_api_key = "test-only"

    def invalid(**kwargs):
        raise ValueError("private configuration details")

    monkeypatch.setattr("app.analysis.provider.ChatGroq", invalid)
    with pytest.raises(AnalysisError, match="model configuration is invalid"):
        await GroqProvider(test_settings).generate({})
