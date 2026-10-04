import os

from ..decision_provider import DeterministicDecisionProvider
from ..provider import DecisionProvider
from .gemini import (
    GeminiDecisionProvider,
    GoogleGenAIStructuredOutputGenerator,
)


def create_decision_provider() -> DecisionProvider:
    provider = os.getenv("DECISION_PROVIDER", "deterministic").strip().casefold()
    if provider == "deterministic":
        return DeterministicDecisionProvider()
    if provider != "gemini":
        raise ValueError(f"Unsupported decision provider: {provider}")

    api_key = os.getenv("GEMINI_API_KEY", "")
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    timeout_value = os.getenv("GEMINI_TIMEOUT_SECONDS", "30")
    try:
        timeout_seconds = float(timeout_value)
    except ValueError as error:
        raise ValueError("GEMINI_TIMEOUT_SECONDS must be a number") from error

    generator = GoogleGenAIStructuredOutputGenerator(
        api_key=api_key,
        model=model,
        timeout_seconds=timeout_seconds,
    )
    return GeminiDecisionProvider(generator)
