"""Async Groq boundary, preserving V1's schema recovery without holding a DB session."""

import json
from typing import Any, Protocol

from groq import BadRequestError
from langchain_core.prompts import PromptTemplate
from langchain_groq import ChatGroq

from app.analysis.errors import AnalysisError
from app.analysis.ported import (
    PROMPT,
    LLMAnalysis,
    _failed_generation,
    _normalize_analysis_payload,
    _schema_failure,
)
from app.core.config import Settings


class AnalysisProvider(Protocol):
    async def generate(self, evidence: dict[str, Any]) -> LLMAnalysis: ...


class GroqProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def generate(self, evidence: dict[str, Any]) -> LLMAnalysis:
        if not self.settings.groq_api_key:
            raise AnalysisError("APP_GROQ_API_KEY is required to run analysis.")
        from pydantic import SecretStr

        model = ChatGroq(
            model=self.settings.groq_model,
            api_key=SecretStr(self.settings.groq_api_key),
            temperature=0,
            timeout=30,
            max_retries=1,
        )
        # The original prompt is unchanged. V2 tightens the boundary for numerical facts.
        prompt = PromptTemplate(
            template=PROMPT
            + "\nV2: Do not include numbers, calculations, URLs or ASINs in prose. Numeric facts are rendered separately by Python. Describe listing claims as claims, not verified performance.",
            input_variables=["evidence"],
        )
        inputs = {"evidence": json.dumps(evidence, ensure_ascii=False)}
        try:
            chain = prompt | model.with_structured_output(
                LLMAnalysis, method="json_schema", strict=True
            )
            result = await chain.ainvoke(inputs)
            return _normalize_analysis_payload(
                result.model_dump() if isinstance(result, LLMAnalysis) else result
            )
        except BadRequestError as exc:
            if not _schema_failure(exc):
                raise AnalysisError(
                    "Groq rejected the request; check the configured model and API key."
                ) from exc
            recovered = _failed_generation(exc)
            if recovered:
                return recovered
            try:
                fallback = prompt | model.with_structured_output(method="json_mode")
                return _normalize_analysis_payload(await fallback.ainvoke(inputs))
            except Exception as fallback_exc:
                raise AnalysisError() from fallback_exc
        except Exception as exc:
            raise AnalysisError(
                "Groq is unavailable or returned invalid output. Please retry."
            ) from exc
