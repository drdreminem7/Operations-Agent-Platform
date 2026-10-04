import pytest

from app.agent.decision_provider import DeterministicDecisionProvider
from app.agent.model_router import RoutedDecisionProvider
from app.agent.providers.factory import create_decision_provider
from app.agent.providers.gemini import (
    GeminiDecisionProvider,
    StructuredDecisionProvider,
)


def test_factory_uses_deterministic_provider_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DECISION_PROVIDER", raising=False)

    provider = create_decision_provider()

    assert isinstance(provider, DeterministicDecisionProvider)


def test_factory_creates_gemini_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DECISION_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    monkeypatch.setenv("GEMINI_TIMEOUT_SECONDS", "5")

    provider = create_decision_provider()

    assert isinstance(provider, GeminiDecisionProvider)


def test_factory_requires_gemini_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DECISION_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(ValueError, match="API key"):
        create_decision_provider()


def test_factory_rejects_invalid_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DECISION_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_TIMEOUT_SECONDS", "soon")

    with pytest.raises(ValueError, match="must be a number"):
        create_decision_provider()


def test_factory_rejects_unknown_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DECISION_PROVIDER", "unknown")

    with pytest.raises(ValueError, match="Unsupported decision provider"):
        create_decision_provider()


def test_factory_creates_routed_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DECISION_PROVIDER", "routed")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_TRIAGE_MODEL", "triage-model")
    monkeypatch.setenv("GEMINI_PLANNING_MODEL", "planning-model")

    assert isinstance(create_decision_provider(), RoutedDecisionProvider)


def test_factory_rejects_same_model_for_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DECISION_PROVIDER", "routed")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_TRIAGE_MODEL", "same-model")
    monkeypatch.setenv("GEMINI_PLANNING_MODEL", "same-model")

    with pytest.raises(ValueError, match="distinct"):
        create_decision_provider()


def test_factory_creates_local_vllm_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DECISION_PROVIDER", "vllm")
    monkeypatch.setenv("VLLM_MODEL", "local-model")
    monkeypatch.setenv("VLLM_BASE_URL", "http://127.0.0.1:8001/v1")

    assert isinstance(create_decision_provider(), StructuredDecisionProvider)


def test_factory_rejects_invalid_vllm_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DECISION_PROVIDER", "vllm")
    monkeypatch.setenv("VLLM_TIMEOUT_SECONDS", "soon")

    with pytest.raises(ValueError, match="VLLM_TIMEOUT_SECONDS must be a number"):
        create_decision_provider()
