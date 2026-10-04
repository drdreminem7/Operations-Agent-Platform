import hmac
import logging
import os

from fastapi import APIRouter, Depends, Header, HTTPException
from opentelemetry import trace

from ..agent.repository import AgentRunRepository
from ..database import engine
from ..models import ApprovalRecord
from ..observability.logging import bind_context, log_event
from ..policy import SYSTEM_ACTOR, PolicyContext, PolicyEngine, PolicyOutcome
from ..schemas import ApprovalResponse

router = APIRouter()
repository = AgentRunRepository(engine)
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


def require_operator(
    x_approval_key: str | None = Header(default=None),
    x_operator_id: str | None = Header(default=None),
) -> str:
    expected = os.getenv("APPROVAL_API_KEY")
    if not expected:
        raise HTTPException(
            status_code=503, detail="Approval API key is not configured"
        )
    if x_approval_key is None or not hmac.compare_digest(x_approval_key, expected):
        raise HTTPException(status_code=403, detail="Invalid approval API key")
    if x_operator_id is None or not x_operator_id.strip() or len(x_operator_id) > 100:
        raise HTTPException(status_code=400, detail="Operator ID is required")
    return x_operator_id.strip()


@router.get("/approvals/pending", response_model=list[ApprovalResponse])
def list_pending_approvals(
    operator_id: str = Depends(require_operator),
) -> list[ApprovalRecord]:
    return repository.list_pending_approvals()


def decide(approval_id: int, *, approved: bool, operator_id: str) -> ApprovalRecord:
    approval = repository.get_approval(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    run = repository.load_run(approval.run_id)
    if run is None or run.action_proposal is None:
        raise HTTPException(status_code=409, detail="Run has no action proposal")
    policy_decision = PolicyEngine().evaluate(
        actor=SYSTEM_ACTOR,
        run_service=run.service,
        tool_name=run.action_proposal.action,
        arguments=run.action_proposal.arguments,
        context=PolicyContext(),
    )
    if policy_decision.outcome != PolicyOutcome.REQUIRE_APPROVAL:
        raise HTTPException(status_code=409, detail="Policy no longer permits approval")
    with (
        bind_context(
            run_id=approval.run_id,
            incident_id=run.incident_id,
            step_id=len(run.history) + 1,
        ),
        tracer.start_as_current_span("approval.decision") as span,
    ):
        span.set_attribute("approval.approved", approved)
        try:
            repository.decide_approval(
                approval_id, approved=approved, decided_by=operator_id
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        log_event(
            logger,
            logging.INFO,
            "approval_decided",
            outcome="approved" if approved else "denied",
        )
    result = repository.get_approval(approval_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    return result


@router.post("/approvals/{approval_id}/approve", response_model=ApprovalResponse)
def approve(
    approval_id: int,
    operator_id: str = Depends(require_operator),
) -> ApprovalRecord:
    return decide(approval_id, approved=True, operator_id=operator_id)


@router.post("/approvals/{approval_id}/deny", response_model=ApprovalResponse)
def deny(
    approval_id: int,
    operator_id: str = Depends(require_operator),
) -> ApprovalRecord:
    return decide(approval_id, approved=False, operator_id=operator_id)
