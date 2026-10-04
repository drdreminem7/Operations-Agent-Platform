import asyncio

import pytest
from pydantic import BaseModel

from app.agent.providers.errors import ModelProviderResponseError
from app.agent.providers.gemini import GeminiDecisionProvider, GeneratedContent
from app.tools.result import ToolResult


class FakeStructuredOutputGenerator:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []
        self.schemas: list[type[BaseModel]] = []

    async def generate(
        self,
        *,
        prompt: str,
        response_schema: type[BaseModel],
    ) -> GeneratedContent:
        self.prompts.append(prompt)
        self.schemas.append(response_schema)
        return GeneratedContent(
            text=self.response,
            model="test-model",
            latency_ms=1,
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
        )


def test_choose_tool_returns_validated_tool_request() -> None:
    generator = FakeStructuredOutputGenerator(
        """
        {
            "tool_name": "search_logs",
            "service": "checkout",
            "query": "error",
            "limit": null,
            "reason": "Search for checkout errors."
        }
        """
    )
    provider = GeminiDecisionProvider(generator)

    request = asyncio.run(
        provider.choose_tool(
            title="Checkout errors increased",
            service="checkout",
        )
    )

    assert request.tool_name == "search_logs"
    assert request.arguments == {
        "service": "checkout",
        "query": "error",
    }
    assert request.trace is not None
    assert request.trace.model == "test-model"
    assert request.trace.total_tokens == 15
    assert "Checkout errors increased" in generator.prompts[0]


def test_tool_prompt_contains_prior_evidence() -> None:
    generator = FakeStructuredOutputGenerator(
        '{"tool_name":"search_logs","service":"checkout",'
        '"query":"timed out","reason":"Inspect logs."}'
    )
    provider = GeminiDecisionProvider(generator)

    asyncio.run(
        provider.choose_tool(
            title="Checkout latency increased after deployment",
            service="checkout",
            evidence=[
                ToolResult(
                    tool_name="get_service_health",
                    output={"service": "checkout", "status": "degraded"},
                )
            ],
        )
    )

    assert "get_service_health" in generator.prompts[0]
    assert "degraded" in generator.prompts[0]


def test_propose_action_returns_validated_proposal() -> None:
    generator = FakeStructuredOutputGenerator(
        """
        {
            "action": "rollback_deployment",
            "service": "checkout",
            "version": "2.4.1",
            "reason": "The deployment correlates with the incident."
        }
        """
    )
    provider = GeminiDecisionProvider(generator)
    evidence = [
        ToolResult(
            tool_name="get_recent_deployments",
            output={
                "deployments": [
                    {
                        "service": "checkout",
                        "version": "2.4.1",
                    }
                ]
            },
        )
    ]

    proposal = asyncio.run(
        provider.propose_action(
            title="Errors started after deployment",
            service="checkout",
            evidence=evidence,
        )
    )

    assert proposal.action == "rollback_deployment"
    assert proposal.arguments["version"] == "2.4.1"
    assert proposal.trace is not None
    assert proposal.trace.provider == "gemini"
    assert "get_recent_deployments" in generator.prompts[0]


def test_invalid_json_becomes_provider_response_error() -> None:
    generator = FakeStructuredOutputGenerator("This is not JSON.")
    provider = GeminiDecisionProvider(generator)

    with pytest.raises(
        ModelProviderResponseError,
        match="invalid decision",
    ):
        asyncio.run(
            provider.choose_tool(
                title="Checkout errors increased",
                service="checkout",
            )
        )


@pytest.mark.parametrize(
    "response",
    [
        '{"tool_name":"search_logs","service":"checkout"}',
        (
            '{"tool_name":"delete_database","service":"checkout",'
            '"reason":"Remove data."}'
        ),
        (
            '{"tool_name":"get_recent_deployments",'
            '"service":"checkout","limit":100,'
            '"reason":"Inspect deployments."}'
        ),
        "Choose search_logs.",
    ],
)
def test_invalid_tool_decisions_are_rejected(response: str) -> None:
    provider = GeminiDecisionProvider(FakeStructuredOutputGenerator(response))

    with pytest.raises(ModelProviderResponseError, match="invalid decision"):
        asyncio.run(
            provider.choose_tool(
                title="Checkout errors increased",
                service="checkout",
            )
        )


def test_model_cannot_control_approval_requirement() -> None:
    generator = FakeStructuredOutputGenerator(
        """
        {
            "action": "rollback_deployment",
            "service": "checkout",
            "version": "2.4.1",
            "reason": "Rollback the deployment.",
            "requires_approval": false
        }
        """
    )
    provider = GeminiDecisionProvider(generator)

    with pytest.raises(
        ModelProviderResponseError,
        match="invalid decision",
    ):
        asyncio.run(
            provider.propose_action(
                title="Errors started after deployment",
                service="checkout",
                evidence=[],
            )
        )


def test_tool_request_cannot_target_another_service() -> None:
    generator = FakeStructuredOutputGenerator(
        """
        {
            "tool_name": "search_logs",
            "service": "payments",
            "query": "error",
            "limit": null,
            "reason": "Search another service."
        }
        """
    )
    provider = GeminiDecisionProvider(generator)

    with pytest.raises(ModelProviderResponseError, match="different service"):
        asyncio.run(
            provider.choose_tool(
                title="Checkout errors increased",
                service="checkout",
            )
        )


def test_rollback_version_must_exist_in_evidence() -> None:
    generator = FakeStructuredOutputGenerator(
        """
        {
            "action": "rollback_deployment",
            "service": "checkout",
            "version": "9.9.9",
            "reason": "Rollback an unobserved version."
        }
        """
    )
    provider = GeminiDecisionProvider(generator)
    evidence = [
        ToolResult(
            tool_name="get_recent_deployments",
            output={
                "deployments": [
                    {"service": "checkout", "version": "2.4.1"}
                ]
            },
        )
    ]

    with pytest.raises(ModelProviderResponseError, match="absent from evidence"):
        asyncio.run(
            provider.propose_action(
                title="Errors started after deployment",
                service="checkout",
                evidence=evidence,
            )
        )
