from typing import Any, NotRequired, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from ..agent.decision_provider import DeterministicDecisionProvider
from ..agent.evidence import supports_rollback
from ..policy import SYSTEM_ACTOR, PolicyContext, PolicyEngine, PolicyOutcome
from ..tools.defaults import create_default_registry
from ..tools.executor import ToolExecutor
from ..tools.result import ToolResult
from ..tools.simulator import Simulator


class GraphState(TypedDict):
    title: str
    service: str
    evidence: NotRequired[list[ToolResult]]
    action: NotRequired[str]
    version: NotRequired[str]
    approved: NotRequired[bool]
    status: NotRequired[str]


def build_workflow(simulator: Simulator) -> Any:
    executor = ToolExecutor(create_default_registry(simulator))
    provider = DeterministicDecisionProvider()
    policy = PolicyEngine()
    context = PolicyContext()

    async def call_tool(
        service: str, name: str, arguments: dict[str, object]
    ) -> ToolResult:
        decision = policy.evaluate(
            actor=SYSTEM_ACTOR,
            run_service=service,
            tool_name=name,
            arguments=arguments,
            context=context,
        )
        if decision.outcome not in {
            PolicyOutcome.ALLOW,
            PolicyOutcome.REQUIRE_APPROVAL,
        }:
            raise ValueError("Policy denied the experiment tool")
        return await executor.execute(
            name, arguments, granted_permissions=decision.granted_permissions
        )

    async def gather(state: GraphState) -> dict[str, object]:
        service = state["service"]
        requests: list[tuple[str, dict[str, object]]] = [
            ("get_service_health", {"service": service}),
            ("get_recent_deployments", {"service": service, "limit": 5}),
            ("search_logs", {"service": service, "query": "timed out"}),
        ]
        evidence = [
            await call_tool(service, name, arguments) for name, arguments in requests
        ]
        return {"evidence": evidence}

    async def plan(state: GraphState) -> dict[str, object]:
        evidence = state["evidence"]
        proposal = await provider.propose_action(
            title=state["title"], service=state["service"], evidence=evidence
        )
        version = proposal.arguments.get("version")
        if (
            proposal.action == "rollback_deployment"
            and isinstance(version, str)
            and supports_rollback(
                evidence, service=state["service"], version=version
            )
        ):
            return {
                "action": "rollback_deployment",
                "version": version,
                "status": "awaiting_approval",
            }
        return {"action": "escalate", "status": "escalated"}

    def review(state: GraphState) -> dict[str, object]:
        approved = interrupt(
            {"action": state["action"], "version": state["version"]}
        )
        if not isinstance(approved, bool):
            raise ValueError("Approval response must be a boolean")
        return {
            "approved": approved,
            "status": "approved" if approved else "escalated",
        }

    async def execute(state: GraphState) -> dict[str, object]:
        if state.get("approved") is not True:
            raise ValueError("Rollback requires approval")
        await call_tool(
            state["service"],
            "rollback_deployment",
            {"service": state["service"], "version": state["version"]},
        )
        return {"status": "executed"}

    async def verify(state: GraphState) -> dict[str, object]:
        service = state["service"]
        health = await call_tool(
            service, "get_service_health", {"service": service}
        )
        deployments = await call_tool(
            service,
            "get_recent_deployments",
            {"service": service, "limit": 5},
        )
        rows = deployments.output.get("deployments")
        rolled_back = isinstance(rows, list) and any(
            isinstance(row, dict)
            and row.get("version") == state["version"]
            and row.get("status") == "rolled_back"
            for row in rows
        )
        status = (
            "resolved"
            if health.output.get("status") == "healthy" and rolled_back
            else "failed"
        )
        return {"status": status}

    builder = StateGraph(GraphState)
    builder.add_node("gather", gather)
    builder.add_node("plan", plan)
    builder.add_node("review", review)
    builder.add_node("execute", execute)
    builder.add_node("verify", verify)
    builder.add_edge(START, "gather")
    builder.add_edge("gather", "plan")
    builder.add_conditional_edges(
        "plan",
        lambda state: "review" if state["action"] == "rollback_deployment" else END,
    )
    builder.add_conditional_edges(
        "review", lambda state: "execute" if state["approved"] else END
    )
    builder.add_edge("execute", "verify")
    builder.add_edge("verify", END)
    return builder.compile(checkpointer=InMemorySaver())
