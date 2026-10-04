import logging
from collections.abc import Callable

from opentelemetry import trace

from ..observability.logging import bind_context, log_event
from ..observability.metrics import approval_requests_total, record_run_terminal
from ..policy import (
    SYSTEM_ACTOR,
    PolicyContext,
    PolicyEngine,
    PolicyOutcome,
)
from ..tools.errors import ToolExecutionError
from ..tools.executor import ToolExecutor
from ..tools.result import ToolResult
from .decision_provider import ActionProposal, ToolRequest
from .provider import DecisionProvider
from .repository import AgentRunRepository
from .run import AgentRun
from .states import RunState

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)
TERMINAL_STATES = {RunState.RESOLVED, RunState.ESCALATED, RunState.FAILED}


class AgentEngine:
    def __init__(
        self,
        decision_provider: DecisionProvider,
        tool_executor: ToolExecutor | None = None,
        repository: AgentRunRepository | None = None,
        *,
        tool_executor_factory: Callable[[AgentRun], ToolExecutor] | None = None,
    ) -> None:
        if tool_executor is None and tool_executor_factory is None:
            raise ValueError("A tool executor or factory is required")
        self._decision_provider = decision_provider
        self._tool_executor = tool_executor
        self._tool_executor_factory = tool_executor_factory
        self._run_executors: dict[int, ToolExecutor] = {}
        self._repository = repository
        self._policy = PolicyEngine()
        self._policy_context = PolicyContext()

    def _executor_for(self, run: AgentRun) -> ToolExecutor:
        if self._tool_executor_factory is None:
            if self._tool_executor is None:
                raise ValueError("No tool executor is configured")
            return self._tool_executor
        key = run.run_id if run.run_id is not None else id(run)
        executor = self._run_executors.get(key)
        if executor is None:
            executor = self._tool_executor_factory(run)
            self._run_executors[key] = executor
        return executor

    def _decision_trace(
        self, decision: ToolRequest | ActionProposal
    ) -> dict[str, object]:
        if decision.trace is not None:
            return decision.trace.model_dump(exclude_none=True)
        return {"provider": type(self._decision_provider).__name__}

    @staticmethod
    def _needs_more_context(run: AgentRun, result: ToolResult) -> bool:
        incident_text = run.title.casefold()
        if "latency" not in incident_text or "deploy" not in incident_text:
            return False
        seen = {item.tool_name for item in run.tool_results}
        if result.tool_name in seen:
            raise ToolExecutionError("Investigation tool was already used for this run")
        required = {
            "get_service_health",
            "get_recent_deployments",
            "search_logs",
        }
        return bool(required - seen - {result.tool_name})

    def _policy_decision(
        self, run: AgentRun, tool_name: str, arguments: dict[str, object]
    ) -> PolicyOutcome:
        return self._policy.evaluate(
            actor=SYSTEM_ACTOR,
            run_service=run.service,
            tool_name=tool_name,
            arguments=arguments,
            context=self._policy_context,
        ).outcome

    def _transition(
        self,
        run: AgentRun,
        next_state: RunState,
        *,
        step_type: str,
        reason: str,
        payload_json: dict[str, object] | None = None,
    ) -> None:
        transition = run.prepare_transition(next_state)

        if self._repository is not None:
            if run.run_id is None:
                raise ValueError("A persisted run must have a database run ID")

            with tracer.start_as_current_span("run.persist_transition"):
                self._repository.record_transition(
                    run.run_id,
                    transition,
                    step_type=step_type,
                    reason=reason,
                    payload_json=payload_json,
                )

        run.apply_transition(transition)
        if next_state == RunState.AWAITING_APPROVAL:
            approval_requests_total.inc()
            trace.get_current_span().add_event("approval.wait_started")
        log_event(
            logger,
            logging.INFO,
            "run_state_changed",
            state_before=transition.state_before.value,
            state_after=transition.state_after.value,
        )
        if next_state in {RunState.RESOLVED, RunState.ESCALATED, RunState.FAILED}:
            key = run.run_id if run.run_id is not None else id(run)
            self._run_executors.pop(key, None)

    async def gather_context(self, run: AgentRun) -> ToolResult:
        if run.current_state != RunState.GATHER_CONTEXT:
            raise ValueError("Run must be in gather_context state")

        request = await self._decision_provider.choose_tool(
            title=run.title,
            service=run.service,
            description=run.description,
            evidence=run.tool_results,
        )

        decision = self._policy.evaluate(
            actor=SYSTEM_ACTOR,
            run_service=run.service,
            tool_name=request.tool_name,
            arguments=request.arguments,
            context=self._policy_context,
        )
        if decision.outcome != PolicyOutcome.ALLOW:
            raise ToolExecutionError(decision.reason)

        result = await self._executor_for(run).execute(
            request.tool_name,
            request.arguments,
            granted_permissions=decision.granted_permissions,
        )

        next_state = (
            RunState.GATHER_CONTEXT
            if self._needs_more_context(run, result)
            else RunState.PLAN
        )

        self._transition(
            run,
            next_state,
            step_type="tool_execution",
            reason=request.reason,
            payload_json={
                "tool_name": result.tool_name,
                "output": result.output,
                "decision_trace": self._decision_trace(request),
            },
        )
        run.tool_results.append(result)
        return result

    async def step(self, run: AgentRun) -> RunState:
        previous = run.current_state
        with (
            bind_context(
                run_id=run.run_id,
                incident_id=run.incident_id,
                step_id=len(run.history) + 1,
            ),
            tracer.start_as_current_span("agent.step") as span,
        ):
            if run.run_id is not None:
                span.set_attribute("run.id", run.run_id)
            span.set_attribute("incident.id", run.incident_id)
            span.set_attribute("run.state_before", previous.value)
            try:
                result = await self._step(run)
            except Exception as error:
                log_event(
                    logger,
                    logging.ERROR,
                    "agent_step_failed",
                    state_before=previous.value,
                    error_type=type(error).__name__,
                )
                raise
            span.set_attribute("run.state_after", result.value)
            if previous not in TERMINAL_STATES and result in TERMINAL_STATES:
                record = (
                    self._repository.get_run(run.run_id)
                    if self._repository is not None and run.run_id is not None
                    else None
                )
                record_run_terminal(
                    result.value,
                    record.started_at if record is not None else None,
                    record.finished_at if record is not None else None,
                )
            log_event(
                logger,
                logging.INFO,
                "agent_step_completed",
                state_before=previous.value,
                state_after=result.value,
            )
            return result

    async def _step(self, run: AgentRun) -> RunState:
        if run.current_state == RunState.NEW:
            self._transition(
                run,
                RunState.TRIAGE,
                step_type="state_transition",
                reason="Start incident triage",
            )
        elif run.current_state == RunState.TRIAGE:
            self._transition(
                run,
                RunState.GATHER_CONTEXT,
                step_type="state_transition",
                reason="Begin gathering incident context",
            )
        elif run.current_state == RunState.GATHER_CONTEXT:
            await self.gather_context(run)
        elif run.current_state == RunState.PLAN:
            proposal = await self._decision_provider.propose_action(
                title=run.title,
                service=run.service,
                evidence=run.tool_results,
            )
            if proposal.action == "escalate":
                next_state = RunState.ESCALATED
                requires_approval = False
                policy_reason = "No automated action proposed"
                policy_outcome = "escalate"
            else:
                decision = self._policy.evaluate(
                    actor=SYSTEM_ACTOR,
                    run_service=run.service,
                    tool_name=proposal.action,
                    arguments=proposal.arguments,
                    context=self._policy_context,
                )
                next_state = (
                    RunState.FAILED
                    if decision.outcome == PolicyOutcome.DENY
                    else RunState.ACTION_SELECTED
                )
                requires_approval = decision.outcome == PolicyOutcome.REQUIRE_APPROVAL
                policy_reason = decision.reason
                policy_outcome = decision.outcome.value

            self._transition(
                run,
                next_state,
                step_type="action_proposal",
                reason=proposal.reason,
                payload_json={
                    "action": proposal.action,
                    "arguments": proposal.arguments,
                    "requires_approval": requires_approval,
                    "policy_outcome": policy_outcome,
                    "policy_reason": policy_reason,
                    "decision_trace": self._decision_trace(proposal),
                },
            )
            run.action_proposal = proposal
        elif run.current_state == RunState.ACTION_SELECTED:
            pending_proposal = run.action_proposal
            if pending_proposal is None:
                raise ValueError("No action proposal is available")

            outcome = self._policy_decision(
                run, pending_proposal.action, pending_proposal.arguments
            )
            if outcome == PolicyOutcome.DENY:
                raise ValueError("Policy now denies the proposed action")

            if outcome == PolicyOutcome.ALLOW:
                self._transition(
                    run,
                    RunState.EXECUTING,
                    step_type="policy_decision",
                    reason="Policy permits this simulated action",
                    payload_json={"action": pending_proposal.action},
                )
                return run.current_state

            self._transition(
                run,
                RunState.AWAITING_APPROVAL,
                step_type="state_transition",
                reason="Request approval for the proposed action",
                payload_json={
                    "action": pending_proposal.action,
                    "arguments": pending_proposal.arguments,
                },
            )
        elif run.current_state == RunState.EXECUTING:
            approved_proposal = run.action_proposal
            if approved_proposal is None:
                raise ValueError("No approved action proposal is available")

            decision = self._policy.evaluate(
                actor=SYSTEM_ACTOR,
                run_service=run.service,
                tool_name=approved_proposal.action,
                arguments=approved_proposal.arguments,
                context=self._policy_context,
            )
            if decision.outcome == PolicyOutcome.DENY:
                raise ValueError("Policy denies the proposed action")
            if (
                self._repository is not None
                and decision.outcome == PolicyOutcome.REQUIRE_APPROVAL
            ):
                if run.run_id is None:
                    raise ValueError("A persisted run must have a database run ID")
                if not self._repository.claim_execution(run.run_id, approved_proposal):
                    run.apply_transition(run.prepare_transition(RunState.FAILED))
                    self._run_executors.pop(run.run_id, None)
                    return run.current_state

            try:
                result = await self._executor_for(run).execute(
                    approved_proposal.action,
                    approved_proposal.arguments,
                    granted_permissions=decision.granted_permissions,
                )
            except ToolExecutionError as error:
                if self._repository is not None and run.run_id is not None:
                    transition = run.prepare_transition(RunState.FAILED)
                    self._repository.record_execution_result(
                        run.run_id,
                        transition,
                        approved_proposal,
                        error=str(error),
                    )
                    run.apply_transition(transition)
                    self._run_executors.pop(run.run_id, None)
                else:
                    self._transition(
                        run,
                        RunState.FAILED,
                        step_type="tool_execution_failed",
                        reason=str(error),
                        payload_json={"action": approved_proposal.action},
                    )
                return run.current_state

            if self._repository is not None and run.run_id is not None:
                transition = run.prepare_transition(RunState.VERIFY)
                self._repository.record_execution_result(
                    run.run_id, transition, approved_proposal, result=result
                )
                run.apply_transition(transition)
            else:
                self._transition(
                    run,
                    RunState.VERIFY,
                    step_type="tool_execution",
                    reason="Executed the approved action in the simulator",
                    payload_json={
                        "tool_name": result.tool_name,
                        "arguments": approved_proposal.arguments,
                        "output": result.output,
                        "simulated": True,
                    },
                )
            run.tool_results.append(result)
        elif run.current_state == RunState.VERIFY:
            verification_proposal = run.action_proposal
            if verification_proposal is None:
                raise ValueError("No action proposal is available to verify")
            health_decision = self._policy.evaluate(
                actor=SYSTEM_ACTOR,
                run_service=run.service,
                tool_name="get_service_health",
                arguments={"service": run.service},
                context=self._policy_context,
            )
            if health_decision.outcome != PolicyOutcome.ALLOW:
                raise ValueError("Policy denies verification read")
            try:
                health = await self._executor_for(run).execute(
                    "get_service_health",
                    {"service": run.service},
                    granted_permissions=health_decision.granted_permissions,
                )
                verified = health.output.get("status") == "healthy"
                evidence: dict[str, object] = {"health": health.output}
                if verification_proposal.action == "rollback_deployment":
                    deployment_decision = self._policy.evaluate(
                        actor=SYSTEM_ACTOR,
                        run_service=run.service,
                        tool_name="get_recent_deployments",
                        arguments={"service": run.service, "limit": 10},
                        context=self._policy_context,
                    )
                    if deployment_decision.outcome != PolicyOutcome.ALLOW:
                        raise ValueError("Policy denies deployment verification")
                    deployments = await self._executor_for(run).execute(
                        "get_recent_deployments",
                        {"service": run.service, "limit": 10},
                        granted_permissions=deployment_decision.granted_permissions,
                    )
                    evidence["deployments"] = deployments.output
                    rows = deployments.output.get("deployments")
                    version = verification_proposal.arguments.get("version")
                    verified = (
                        verified
                        and isinstance(rows, list)
                        and any(
                            isinstance(row, dict)
                            and row.get("service") == run.service
                            and row.get("version") == version
                            and row.get("status") == "rolled_back"
                            for row in rows
                        )
                    )
            except ToolExecutionError as error:
                self._transition(
                    run,
                    RunState.FAILED,
                    step_type="verification_failed",
                    reason=str(error),
                    payload_json={"result": "tool_error"},
                )
                return run.current_state

            self._transition(
                run,
                RunState.RESOLVED if verified else RunState.FAILED,
                step_type="verification",
                reason=(
                    "Simulator confirms recovery"
                    if verified
                    else "Simulator did not confirm recovery"
                ),
                payload_json={
                    "result": "verified" if verified else "not_verified",
                    "evidence": evidence,
                },
            )
        else:
            raise ValueError(
                f"No automatic step is implemented from state: "
                f"{run.current_state.value}"
            )

        return run.current_state

    def decide_approval(
        self, run: AgentRun, *, approved: bool, decided_by: str = "local_operator"
    ) -> RunState:
        if run.current_state != RunState.AWAITING_APPROVAL:
            raise ValueError("Run is not awaiting approval")

        proposal = run.action_proposal
        if proposal is None:
            raise ValueError("Run has no action proposal")

        policy_outcome = self._policy_decision(run, proposal.action, proposal.arguments)
        if policy_outcome != PolicyOutcome.REQUIRE_APPROVAL:
            raise ValueError("Run has no approval-required action proposal")

        if approved:
            next_state = RunState.EXECUTING
            reason = "Approval granted"
        else:
            next_state = RunState.ESCALATED
            reason = "Approval denied; escalate for human handling"

        if self._repository is not None:
            if run.run_id is None:
                raise ValueError("A persisted run must have a database run ID")
            approval = self._repository.get_approval_for_run(run.run_id)
            if approval is None:
                raise ValueError("Approval record not found")
            transition = run.prepare_transition(next_state)
            self._repository.decide_approval(
                approval.id, approved=approved, decided_by=decided_by
            )
            run.apply_transition(transition)
            if not approved:
                self._run_executors.pop(run.run_id, None)
        else:
            self._transition(
                run,
                next_state,
                step_type="approval_decision",
                reason=reason,
                payload_json={"approved": approved},
            )
        return run.current_state
