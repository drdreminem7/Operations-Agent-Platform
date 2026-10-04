import pytest

from app.agent.decision_provider import DeterministicDecisionProvider
from app.agent.providers.factory import create_decision_provider
from app.agent.providers.gemini import GeminiDecisionProvider


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
