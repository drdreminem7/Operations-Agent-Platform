import asyncio
import json

import httpx
import pytest

from app.agent.providers.errors import (
    ModelProviderError,
    ModelProviderResponseError,
    ModelProviderTimeoutError,
)
from app.agent.providers.gemini import StructuredDecisionProvider
from app.agent.providers.vllm import VLLMStructuredOutputGenerator


def test_vllm_adapter_requests_and_validates_structured_tool_decision() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer local-test-key"
        body = json.loads(request.content)
        assert body["model"] == "local-model"
        assert body["response_format"]["type"] == "json_schema"
        return httpx.Response(
            200,
            json={
                "model": "local-model",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "tool_name": "get_service_health",
                                    "service": "checkout",
                                    "reason": "Inspect current health",
                                }
                            )
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 42,
                    "completion_tokens": 16,
                    "total_tokens": 58,
                },
            },
        )

    generator = VLLMStructuredOutputGenerator(
        base_url="http://127.0.0.1:8001/v1",
        model="local-model",
        api_key="local-test-key",
        transport=httpx.MockTransport(respond),
    )
    provider = StructuredDecisionProvider(generator, provider_name="vLLM")

    decision = asyncio.run(
        provider.choose_tool(title="Checkout latency", service="checkout")
    )

    assert decision.tool_name == "get_service_health"
    assert decision.trace is not None
    assert decision.trace.provider == "vllm"
    assert decision.trace.model == "local-model"
    assert decision.trace.input_tokens == 42
    assert decision.trace.output_tokens == 16


def test_vllm_adapter_rejects_empty_completion() -> None:
    generator = VLLMStructuredOutputGenerator(
        base_url="http://127.0.0.1:8001/v1",
        model="local-model",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"choices": []})
        ),
    )
    provider = StructuredDecisionProvider(generator, provider_name="vLLM")

    with pytest.raises(ModelProviderResponseError, match="no choices"):
        asyncio.run(provider.choose_tool(title="Checkout latency", service="checkout"))


def test_vllm_adapter_maps_timeout() -> None:
    def time_out(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("injected timeout")

    generator = VLLMStructuredOutputGenerator(
        base_url="http://127.0.0.1:8001/v1",
        model="local-model",
        transport=httpx.MockTransport(time_out),
    )
    provider = StructuredDecisionProvider(generator, provider_name="vLLM")

    with pytest.raises(ModelProviderTimeoutError, match="timed out"):
        asyncio.run(provider.choose_tool(title="Checkout latency", service="checkout"))


@pytest.mark.parametrize("status", [429, 500])
def test_vllm_adapter_maps_http_failure_without_leaking_body(status: int) -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, text="private upstream detail")

    generator = VLLMStructuredOutputGenerator(
        base_url="http://127.0.0.1:8001/v1",
        model="local-model",
        transport=httpx.MockTransport(respond),
    )
    provider = StructuredDecisionProvider(generator, provider_name="vLLM")

    with pytest.raises(ModelProviderError, match="vLLM request failed") as error:
        asyncio.run(provider.choose_tool(title="Checkout latency", service="checkout"))

    assert "private upstream detail" not in str(error.value)
    assert calls == 1


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("not json", "malformed JSON"),
        ('{"choices": [{}]}', "no message"),
        ('{"choices": [{"message": {"content": ""}}]}', "empty content"),
    ],
)
def test_vllm_adapter_rejects_malformed_or_partial_response(
    body: str, message: str
) -> None:
    generator = VLLMStructuredOutputGenerator(
        base_url="http://127.0.0.1:8001/v1",
        model="local-model",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=body)
        ),
    )
    provider = StructuredDecisionProvider(generator, provider_name="vLLM")

    with pytest.raises(ModelProviderResponseError, match=message):
        asyncio.run(provider.choose_tool(title="Checkout latency", service="checkout"))


def test_vllm_adapter_maps_connection_failure() -> None:
    def disconnect(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("injected disconnect")

    generator = VLLMStructuredOutputGenerator(
        base_url="http://127.0.0.1:8001/v1",
        model="local-model",
        transport=httpx.MockTransport(disconnect),
    )
    provider = StructuredDecisionProvider(generator, provider_name="vLLM")

    with pytest.raises(ModelProviderError, match="vLLM request failed"):
        asyncio.run(provider.choose_tool(title="Checkout latency", service="checkout"))


@pytest.mark.parametrize(
    ("url", "key", "message"),
    [
        ("http://model.example/v1", "key", "requires HTTPS"),
        ("https://model.example/v1", "", "requires an API key"),
        ("http://127.0.0.1:8001/other", "", "end in /v1"),
    ],
)
def test_vllm_adapter_rejects_unsafe_endpoint_configuration(
    url: str, key: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        VLLMStructuredOutputGenerator(
            base_url=url, model="local-model", api_key=key
        )


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf")])
def test_vllm_adapter_rejects_invalid_timeout(timeout: float) -> None:
    with pytest.raises(ValueError, match="finite positive"):
        VLLMStructuredOutputGenerator(
            base_url="http://127.0.0.1:8001/v1",
            model="local-model",
            timeout_seconds=timeout,
        )
