import asyncio

from app.agent.decision_provider import (
    ActionProposal,
    DeterministicDecisionProvider,
    ToolRequest,
)
from app.tools.result import ToolResult


def test_latency_in_title_requests_service_health() -> None:
    provider = DeterministicDecisionProvider()

    request = asyncio.run(
        provider.choose_tool(
            title="Checkout latency is high",
            service="checkout",
        )
    )

    assert request == ToolRequest(
        tool_name="get_service_health",
        arguments={"service": "checkout"},
        reason="The incident mentions latency, so inspect service health.",
    )


def test_latency_in_description_requests_service_health() -> None:
    provider = DeterministicDecisionProvider()

    request = asyncio.run(
        provider.choose_tool(
            title="Slow checkout",
            service="checkout",
            description="Users are experiencing high LATENCY.",
        )
    )

    assert request.tool_name == "get_service_health"


def test_other_incident_requests_log_search() -> None:
    provider = DeterministicDecisionProvider()

    request = asyncio.run(
        provider.choose_tool(
            title="Checkout errors increased",
            service="checkout",
        )
    )

    assert request == ToolRequest(
        tool_name="search_logs",
        arguments={"service": "checkout", "query": "error"},
        reason="No latency clue was found, so search the service logs for errors.",
    )


def test_deployment_incident_requests_recent_deployments() -> None:
    provider = DeterministicDecisionProvider()

    request = asyncio.run(
        provider.choose_tool(
            title="Errors started after deployment",
            service="checkout",
        )
    )

    assert request == ToolRequest(
        tool_name="get_recent_deployments",
        arguments={"service": "checkout", "limit": 5},
        reason=("The incident mentions a deployment, so inspect recent deployments."),
    )


def test_combined_incident_requests_distinct_evidence_in_order() -> None:
    provider = DeterministicDecisionProvider()
    title = "Checkout latency increased after deployment"
    evidence: list[ToolResult] = []

    for expected_name in (
        "get_service_health",
        "get_recent_deployments",
        "search_logs",
    ):
        request = asyncio.run(
            provider.choose_tool(
                title=title,
                service="checkout",
                evidence=evidence,
            )
        )
        assert request.tool_name == expected_name
        evidence.append(ToolResult(tool_name=request.tool_name, output={}))


def test_recent_production_deployment_proposes_rollback_for_approval() -> None:
    provider = DeterministicDecisionProvider()
    evidence = [
        ToolResult(
            tool_name="get_recent_deployments",
            output={
                "service": "checkout",
                "deployments": [
                    {
                        "service": "checkout",
                        "version": "2.4.1",
                        "environment": "production",
                        "status": "successful",
                    }
                ],
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

    assert proposal == ActionProposal(
        action="rollback_deployment",
        arguments={"service": "checkout", "version": "2.4.1"},
        reason=(
            "A recent production deployment exists and the incident mentions "
            "a deployment; propose rollback for human review."
        ),
    )


def test_insufficient_evidence_proposes_escalation() -> None:
    provider = DeterministicDecisionProvider()

    proposal = asyncio.run(
        provider.propose_action(
            title="Checkout errors increased",
            service="checkout",
            evidence=[],
        )
    )

    assert proposal == ActionProposal(
        action="escalate",
        arguments={"service": "checkout"},
        reason="The simulated evidence is insufficient to safely act.",
    )
