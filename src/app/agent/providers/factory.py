import os

from ..decision_provider import DeterministicDecisionProvider
from ..model_router import RoutedDecisionProvider
from ..provider import DecisionProvider
from .gemini import (
    GeminiDecisionProvider,
    GoogleGenAIStructuredOutputGenerator,
    StructuredDecisionProvider,
)
from .vllm import VLLMStructuredOutputGenerator


def create_decision_provider() -> DecisionProvider:
    provider = os.getenv("DECISION_PROVIDER", "deterministic").strip().casefold()
    if provider == "deterministic":
        return DeterministicDecisionProvider()
    if provider == "vllm":
        timeout_value = os.getenv("VLLM_TIMEOUT_SECONDS", "30")
        try:
            timeout_seconds = float(timeout_value)
        except ValueError as error:
            raise ValueError("VLLM_TIMEOUT_SECONDS must be a number") from error
        return StructuredDecisionProvider(
            VLLMStructuredOutputGenerator(
                base_url=os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8001/v1"),
                model=os.getenv("VLLM_MODEL", ""),
                api_key=os.getenv("VLLM_API_KEY", ""),
                timeout_seconds=timeout_seconds,
            ),
            provider_name="vLLM",
        )
    if provider not in {"gemini", "routed"}:
        raise ValueError(f"Unsupported decision provider: {provider}")

    api_key = os.getenv("GEMINI_API_KEY", "")
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    timeout_value = os.getenv("GEMINI_TIMEOUT_SECONDS", "30")
    try:
        timeout_seconds = float(timeout_value)
    except ValueError as error:
        raise ValueError("GEMINI_TIMEOUT_SECONDS must be a number") from error

    if provider == "gemini":
        generator = GoogleGenAIStructuredOutputGenerator(
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
        )
        return GeminiDecisionProvider(generator)

    triage_model = os.getenv("GEMINI_TRIAGE_MODEL", "").strip()
    planning_model = os.getenv("GEMINI_PLANNING_MODEL", "").strip()
    if not triage_model or not planning_model:
        raise ValueError("Routed mode requires both Gemini model names")
    if triage_model == planning_model:
        raise ValueError("Routed mode requires distinct Gemini models")
    triage = GeminiDecisionProvider(
        GoogleGenAIStructuredOutputGenerator(
            api_key=api_key,
            model=triage_model,
            timeout_seconds=timeout_seconds,
        )
    )
    planning = GeminiDecisionProvider(
        GoogleGenAIStructuredOutputGenerator(
            api_key=api_key,
            model=planning_model,
            timeout_seconds=timeout_seconds,
        )
    )
    return RoutedDecisionProvider(triage, planning)
