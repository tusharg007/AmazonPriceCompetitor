"""The Groq boundary is mocked; no keys or external requests are used."""

import ast
from pathlib import Path

import httpx
import pytest
from app.analysis.errors import AnalysisError
from app.analysis.ported import PROMPT, LLMAnalysis, _failed_generation
from app.analysis.provider import GroqProvider
from groq import BadRequestError
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
