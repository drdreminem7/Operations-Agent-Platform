from datetime import UTC, datetime, timedelta

from opentelemetry import propagate, trace
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ..models import (
    ActionExecutionRecord,
    AgentRunRecord,
    ApprovalRecord,
    Incident,
    RunJobRecord,
    RunStepRecord,
)
from ..observability.metrics import (
    agent_runs_total,
    approval_denials_total,
    record_run_terminal,
)
from ..tools.result import ToolResult
from .approval import action_hash
from .decision_provider import ActionProposal
from .run import AgentRun, RunTransition
from .states import RunState

tracer = trace.get_tracer(__name__)


class AgentRunRepository:
    def __init__(self, db_engine: Engine) -> None:
        self._engine = db_engine

    def create_run(self, incident_id: int, *, enqueue: bool = False) -> int:
        carrier: dict[str, str] = {}
        propagate.inject(carrier)
        with Session(self._engine) as session:
            with session.begin():
                run_record = AgentRunRecord(
                    incident_id=incident_id,
                    status="running",
                    current_state=RunState.NEW.value,
                )
                session.add(run_record)
                session.flush()
                if enqueue:
                    session.add(
                        RunJobRecord(
                            run_id=run_record.id,
                            status="queued",
                            available_at=datetime.now(UTC),
                            traceparent=carrier.get("traceparent"),
                        )
                    )
            agent_runs_total.inc()
            return run_record.id

    def get_run(self, run_id: int) -> AgentRunRecord | None:
        with Session(self._engine) as session:
            return session.get(AgentRunRecord, run_id)

    def get_execution(self, run_id: int) -> ActionExecutionRecord | None:
        with Session(self._engine) as session:
            return session.scalar(
                select(ActionExecutionRecord).where(
                    ActionExecutionRecord.run_id == run_id
                )
            )

    def claim_execution(self, run_id: int, proposal: ActionProposal) -> bool:
        with tracer.start_as_current_span("run.claim_execution"):
            return self._claim_execution(run_id, proposal)

    def _claim_execution(self, run_id: int, proposal: ActionProposal) -> bool:
        claimed = False
        key = action_hash(run_id, proposal.action, proposal.arguments)
        with Session(self._engine) as session:
            with session.begin():
                run_record = session.get(AgentRunRecord, run_id, with_for_update=True)
                if run_record is None or run_record.current_state != RunState.EXECUTING:
                    raise ValueError("Run is not in executing state")

                now = datetime.now(UTC)
                execution = session.scalar(
                    select(ActionExecutionRecord)
                    .where(ActionExecutionRecord.run_id == run_id)
                    .with_for_update()
                )
                if execution is None:
                    approval = session.scalar(
                        select(ApprovalRecord).where(ApprovalRecord.run_id == run_id)
                    )
                    if approval is None or approval.status != "approved":
                        raise ValueError("No approved action exists for this run")
                    if approval.expires_at <= now:
                        raise ValueError("Approval has expired")
                    if approval.action_hash != key:
                        raise ValueError(
                            "Approved action differs from the proposed action"
                        )
                    if key != action_hash(
                        run_id, approval.tool_name, approval.arguments_json
                    ):
                        raise ValueError("Approval record differs from frozen action")
                    session.add(
                        ActionExecutionRecord(
                            run_id=run_id,
                            idempotency_key=key,
                            tool_name=proposal.action,
                            arguments_json=proposal.arguments,
                            status="started",
                            started_at=now,
                        )
                    )
                    claimed = True
                elif (
                    execution.idempotency_key != key
                    or execution.tool_name != proposal.action
                    or execution.arguments_json != proposal.arguments
                ):
                    raise ValueError("Execution action differs from saved action")
                elif execution.status == "started":
                    if now - execution.started_at < timedelta(seconds=10):
                        raise ValueError("Execution is already in progress")
                    execution.status = "uncertain"
                    execution.error = "Execution result was not persisted"
                    execution.finished_at = now
                    run_record.current_state = RunState.FAILED.value
                    run_record.status = "failed"
                    run_record.finished_at = now
                    last_sequence = session.scalar(
                        select(RunStepRecord.sequence_number)
                        .where(RunStepRecord.run_id == run_id)
                        .order_by(RunStepRecord.sequence_number.desc())
                        .limit(1)
                    )
                    session.add(
                        RunStepRecord(
                            run_id=run_id,
                            sequence_number=(last_sequence or 0) + 1,
                            state_before=RunState.EXECUTING.value,
                            state_after=RunState.FAILED.value,
                            step_type="execution_uncertain",
                            reason="Execution result was not persisted",
                            payload_json={"idempotency_key": key},
                        )
                    )
                else:
                    raise ValueError("Execution has already been recorded")
        return claimed

    def record_execution_result(
        self,
        run_id: int,
        transition: RunTransition,
        proposal: ActionProposal,
        *,
        result: ToolResult | None = None,
        error: str | None = None,
    ) -> None:
        with tracer.start_as_current_span("run.persist_execution_result"):
            self._record_execution_result(
                run_id, transition, proposal, result=result, error=error
            )

    def _record_execution_result(
        self,
        run_id: int,
        transition: RunTransition,
        proposal: ActionProposal,
        *,
        result: ToolResult | None = None,
        error: str | None = None,
    ) -> None:
        if (result is None) == (error is None):
            raise ValueError("Exactly one execution result or error is required")
        key = action_hash(run_id, proposal.action, proposal.arguments)
        with Session(self._engine) as session:
            with session.begin():
                run_record = session.get(AgentRunRecord, run_id, with_for_update=True)
                execution = session.scalar(
                    select(ActionExecutionRecord)
                    .where(ActionExecutionRecord.run_id == run_id)
                    .with_for_update()
                )
                if (
                    run_record is None
                    or run_record.current_state != transition.state_before.value
                    or execution is None
                    or execution.status != "started"
                    or execution.idempotency_key != key
                    or execution.tool_name != proposal.action
                    or execution.arguments_json != proposal.arguments
                ):
                    raise ValueError("Execution state changed before persistence")

                now = datetime.now(UTC)
                execution.finished_at = now
                run_record.current_state = transition.state_after.value
                if result is not None:
                    if transition.state_after != RunState.VERIFY:
                        raise ValueError("Successful execution must enter verification")
                    execution.status = "succeeded"
                    execution.result_json = result.output
                    step_type = "tool_execution"
                    reason = "Executed the approved action in the simulator"
                    payload_json: dict[str, object] = {
                        "tool_name": result.tool_name,
                        "arguments": proposal.arguments,
                        "output": result.output,
                        "idempotency_key": key,
                        "simulated": True,
                    }
                else:
                    if transition.state_after != RunState.FAILED:
                        raise ValueError("Uncertain execution must fail the run")
                    execution.status = "uncertain"
                    execution.error = error
                    run_record.status = "failed"
                    run_record.finished_at = now
                    step_type = "execution_uncertain"
                    reason = error or "Execution outcome is uncertain"
                    payload_json = {"idempotency_key": key}

                session.add(
                    RunStepRecord(
                        run_id=run_id,
                        sequence_number=transition.sequence_number,
                        state_before=transition.state_before.value,
                        state_after=transition.state_after.value,
                        step_type=step_type,
                        reason=reason,
                        payload_json=payload_json,
                    )
                )

    def record_transition(
        self,
        run_id: int,
        transition: RunTransition,
        *,
        step_type: str,
        reason: str,
        payload_json: dict[str, object] | None = None,
    ) -> None:
        with Session(self._engine) as session:
            with session.begin():
                run_record = session.get(AgentRunRecord, run_id, with_for_update=True)

                if run_record is None:
                    raise ValueError(f"Run not found: {run_id}")

                if run_record.current_state != transition.state_before.value:
                    raise ValueError(
                        "Run state changed; transition does not start "
                        "from the persisted current state"
                    )

                if transition.state_before == RunState.AWAITING_APPROVAL:
                    raise ValueError("Approval decisions require the approval record")

                if transition.state_after == RunState.AWAITING_APPROVAL:
                    if payload_json is None:
                        raise ValueError("Approval request is missing its action")
                    tool_name = payload_json.get("action")
                    arguments = payload_json.get("arguments")
                    if not isinstance(tool_name, str) or not isinstance(
                        arguments, dict
                    ):
                        raise ValueError("Approval request is invalid")
                    if (
                        session.scalar(
                            select(ApprovalRecord).where(
                                ApprovalRecord.run_id == run_id
                            )
                        )
                        is not None
                    ):
                        raise ValueError("Approval already requested for this run")
                    requested_at = datetime.now(UTC)
                    session.add(
                        ApprovalRecord(
                            run_id=run_id,
                            tool_name=tool_name,
                            arguments_json=arguments,
                            action_hash=action_hash(run_id, tool_name, arguments),
                            status="pending",
                            requested_at=requested_at,
                            expires_at=requested_at + timedelta(minutes=15),
                        )
                    )

                run_record.current_state = transition.state_after.value

                if transition.state_after == RunState.AWAITING_APPROVAL:
                    run_record.status = "awaiting_approval"
                elif transition.state_after == RunState.RESOLVED:
                    run_record.status = "completed"
                    run_record.finished_at = datetime.now(UTC)
                    incident = session.get(Incident, run_record.incident_id)
                    if incident is None:
                        raise ValueError("Incident for run no longer exists")
                    incident.status = "resolved"
                elif transition.state_after == RunState.ESCALATED:
                    run_record.status = "escalated"
                    run_record.finished_at = datetime.now(UTC)
                elif transition.state_after == RunState.FAILED:
                    run_record.status = "failed"
                    run_record.finished_at = datetime.now(UTC)
                else:
                    run_record.status = "running"

                session.add(
                    RunStepRecord(
                        run_id=run_id,
                        sequence_number=transition.sequence_number,
                        state_before=transition.state_before.value,
                        state_after=transition.state_after.value,
                        step_type=step_type,
                        reason=reason,
                        payload_json=payload_json,
                    )
                )

    def get_approval(self, approval_id: int) -> ApprovalRecord | None:
        with Session(self._engine) as session:
            return session.get(ApprovalRecord, approval_id)

    def get_approval_for_run(self, run_id: int) -> ApprovalRecord | None:
        with Session(self._engine) as session:
            return session.scalar(
                select(ApprovalRecord).where(ApprovalRecord.run_id == run_id)
            )

    def list_pending_approvals(self) -> list[ApprovalRecord]:
        with Session(self._engine) as session:
            statement = (
                select(ApprovalRecord)
                .where(
                    ApprovalRecord.status == "pending",
                    ApprovalRecord.expires_at > datetime.now(UTC),
                )
                .order_by(ApprovalRecord.requested_at, ApprovalRecord.id)
            )
            return list(session.scalars(statement).all())

    def decide_approval(
        self, approval_id: int, *, approved: bool, decided_by: str
    ) -> int:
        expired = False
        run_id = 0
        with Session(self._engine) as session:
            with session.begin():
                approval = session.get(
                    ApprovalRecord, approval_id, with_for_update=True
                )
                if approval is None:
                    raise LookupError("Approval not found")
                if approval.status != "pending":
                    raise ValueError("Approval has already been decided")

                run_id = approval.run_id
                run_record = session.get(AgentRunRecord, run_id, with_for_update=True)
                if (
                    run_record is None
                    or run_record.current_state != RunState.AWAITING_APPROVAL.value
                ):
                    raise ValueError("Run is not awaiting approval")

                now = datetime.now(UTC)
                if approval.expires_at <= now:
                    approval.status = "expired"
                    expired = True
                else:
                    proposal_step = session.scalar(
                        select(RunStepRecord)
                        .where(
                            RunStepRecord.run_id == run_id,
                            RunStepRecord.step_type == "action_proposal",
                        )
                        .order_by(RunStepRecord.sequence_number.desc())
                        .limit(1)
                    )
                    payload = proposal_step.payload_json if proposal_step else None
                    tool_name = (
                        payload.get("action") if isinstance(payload, dict) else None
                    )
                    arguments = (
                        payload.get("arguments") if isinstance(payload, dict) else None
                    )
                    if not isinstance(tool_name, str) or not isinstance(
                        arguments, dict
                    ):
                        raise ValueError("Saved action proposal is invalid")
                    if approval.action_hash != action_hash(
                        run_id, approval.tool_name, approval.arguments_json
                    ):
                        raise ValueError("Approval record differs from frozen action")
                    if approval.action_hash != action_hash(
                        run_id, tool_name, arguments
                    ):
                        raise ValueError("Approval action differs from saved proposal")

                    next_state = RunState.EXECUTING if approved else RunState.ESCALATED
                    approval.status = "approved" if approved else "denied"
                    approval.decided_at = now
                    approval.decided_by = decided_by
                    run_record.current_state = next_state.value
                    run_record.status = "running" if approved else "escalated"
                    if not approved:
                        run_record.finished_at = now

                    job = session.scalar(
                        select(RunJobRecord)
                        .where(RunJobRecord.run_id == run_id)
                        .with_for_update()
                    )
                    if job is not None and job.status == "paused":
                        job.status = "queued" if approved else "completed"
                        job.available_at = now

                    last_sequence = session.scalar(
                        select(RunStepRecord.sequence_number)
                        .where(RunStepRecord.run_id == run_id)
                        .order_by(RunStepRecord.sequence_number.desc())
                        .limit(1)
                    )
                    session.add(
                        RunStepRecord(
                            run_id=run_id,
                            sequence_number=(last_sequence or 0) + 1,
                            state_before=RunState.AWAITING_APPROVAL.value,
                            state_after=next_state.value,
                            step_type="approval_decision",
                            reason=(
                                "Approval granted"
                                if approved
                                else "Approval denied; escalate for human handling"
                            ),
                            payload_json={
                                "approval_id": approval.id,
                                "approved": approved,
                                "decided_by": decided_by,
                            },
                        )
                    )
        if expired:
            raise ValueError("Approval has expired")
        if not approved:
            approval_denials_total.inc()
            completed = self.get_run(run_id)
            if completed is not None:
                record_run_terminal(
                    completed.current_state,
                    completed.started_at,
                    completed.finished_at,
                )
        return run_id

    def list_steps(self, run_id: int) -> list[RunStepRecord]:
        statement = (
            select(RunStepRecord)
            .where(RunStepRecord.run_id == run_id)
            .order_by(RunStepRecord.sequence_number)
        )

        with Session(self._engine) as session:
            return list(session.scalars(statement).all())

    def load_run(self, run_id: int) -> AgentRun | None:
        with Session(self._engine) as session:
            run_record = session.get(AgentRunRecord, run_id)

            if run_record is None:
                return None

            incident = session.get(Incident, run_record.incident_id)
            if incident is None:
                raise ValueError(
                    f"Incident not found for persisted run: {run_record.id}"
                )

            statement = (
                select(RunStepRecord)
                .where(RunStepRecord.run_id == run_id)
                .order_by(RunStepRecord.sequence_number)
            )
            saved_steps = list(session.scalars(statement).all())

            run = AgentRun(
                run_id=run_record.id,
                incident_id=incident.id,
                title=incident.title,
                service=incident.service,
                description=incident.description,
                current_state=RunState(run_record.current_state),
            )

            for saved_step in saved_steps:
                run.history.append(
                    RunTransition(
                        sequence_number=saved_step.sequence_number,
                        state_before=RunState(saved_step.state_before),
                        state_after=RunState(saved_step.state_after),
                    )
                )

                payload = saved_step.payload_json
                if not isinstance(payload, dict):
                    continue

                if saved_step.step_type == "tool_execution":
                    tool_name = payload.get("tool_name")
                    output = payload.get("output")

                    if isinstance(tool_name, str) and isinstance(output, dict):
                        run.tool_results.append(
                            ToolResult(tool_name=tool_name, output=output)
                        )

                if saved_step.step_type == "action_proposal":
                    action = payload.get("action")
                    arguments = payload.get("arguments")

                    if isinstance(action, str) and isinstance(arguments, dict):
                        run.action_proposal = ActionProposal.model_validate(
                            {
                                "action": action,
                                "arguments": arguments,
                                "reason": saved_step.reason,
                            }
                        )
            return run
