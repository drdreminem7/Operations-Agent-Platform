import asyncio
import logging

import pytest
from google.genai import types
from pydantic import BaseModel

from app.agent.providers.errors import (
    ModelProviderError,
    ModelProviderResponseError,
    ModelProviderTimeoutError,
)
from app.agent.providers.gemini import (
    GeminiResponse,
    GoogleGenAIStructuredOutputGenerator,
)


class ExampleResponse(BaseModel):
    value: str


class FakeResponse:
    def __init__(self, text: str | None) -> None:
        self.text = text
        self.model_version: str | None = "test-model-v1"
        self.usage_metadata: types.GenerateContentResponseUsageMetadata | None = (
            types.GenerateContentResponseUsageMetadata(
                prompt_token_count=12,
                candidates_token_count=7,
                total_token_count=19,
            )
        )


class UnreadableResponse:
    model_version: str | None = "test-model-v1"
    usage_metadata: types.GenerateContentResponseUsageMetadata | None = None

    @property
    def text(self) -> str:
        raise ValueError("unavailable")


class FakeGenerateContent:
    def __init__(
        self,
        *,
        response: GeminiResponse | None = None,
        error: Exception | None = None,
        delay_seconds: float = 0,
    ) -> None:
        self.response = response
        self.error = error
        self.delay_seconds = delay_seconds
        self.calls: list[dict[str, object]] = []

    async def __call__(
        self,
        *,
        model: str,
        contents: str,
        config: types.GenerateContentConfig,
    ) -> GeminiResponse:
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.error is not None:
            raise self.error
        if self.response is None:
            raise AssertionError("response not configured")
        return self.response


def make_generator(
    generate_content: FakeGenerateContent,
    *,
    timeout_seconds: float = 30,
) -> GoogleGenAIStructuredOutputGenerator:
    return GoogleGenAIStructuredOutputGenerator(
        api_key="",
        model="test-model",
        timeout_seconds=timeout_seconds,
        generate_content=generate_content,
    )


def test_generator_returns_usage_and_logs_call(
    caplog: pytest.LogCaptureFixture,
) -> None:
    call = FakeGenerateContent(response=FakeResponse('{"value":"ok"}'))
    generator = make_generator(call)
    caplog.set_level(logging.INFO)

    result = asyncio.run(
        generator.generate(
            prompt="Return a value.",
            response_schema=ExampleResponse,
        )
    )

    assert result.text == '{"value":"ok"}'
    assert result.model == "test-model-v1"
    assert result.input_tokens == 12
    assert result.output_tokens == 7
    assert result.total_tokens == 19
    assert result.latency_ms >= 0
    assert call.calls[0]["model"] == "test-model"
    assert "model_call_completed" in caplog.text


def test_generator_rejects_empty_response() -> None:
    generator = make_generator(FakeGenerateContent(response=FakeResponse(None)))

    with pytest.raises(ModelProviderResponseError, match="structured output"):
        asyncio.run(
            generator.generate(
                prompt="Return a value.",
                response_schema=ExampleResponse,
            )
        )


def test_generator_rejects_unreadable_response() -> None:
    generator = make_generator(FakeGenerateContent(response=UnreadableResponse()))

    with pytest.raises(ModelProviderResponseError, match="readable text"):
        asyncio.run(
            generator.generate(
                prompt="Return a value.",
                response_schema=ExampleResponse,
            )
        )


def test_generator_translates_sdk_error() -> None:
    generator = make_generator(
        FakeGenerateContent(error=RuntimeError("provider unavailable"))
    )

    with pytest.raises(ModelProviderError, match="request failed"):
        asyncio.run(
            generator.generate(
                prompt="Return a value.",
                response_schema=ExampleResponse,
            )
        )


def test_generator_times_out() -> None:
    generator = make_generator(
        FakeGenerateContent(
            response=FakeResponse('{"value":"late"}'),
            delay_seconds=0.05,
        ),
        timeout_seconds=0.001,
    )

    with pytest.raises(ModelProviderTimeoutError, match="timeout"):
        asyncio.run(
            generator.generate(
                prompt="Return a value.",
                response_schema=ExampleResponse,
            )
        )


@pytest.mark.parametrize(
    ("api_key", "model", "timeout_seconds", "message"),
    [
        ("", "test-model", 30, "API key"),
        ("test-key", "", 30, "model"),
        ("test-key", "test-model", 0, "greater than zero"),
        ("test-key", "test-model", float("nan"), "finite"),
        ("test-key", "test-model", float("inf"), "finite"),
    ],
)
def test_generator_rejects_invalid_configuration(
    api_key: str,
    model: str,
    timeout_seconds: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        GoogleGenAIStructuredOutputGenerator(
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
        )
