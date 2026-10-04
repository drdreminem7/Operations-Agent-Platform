from enum import StrEnum


class RunState(StrEnum):
    NEW = "new"
    TRIAGE = "triage"
    GATHER_CONTEXT = "gather_context"
    PLAN = "plan"
    ACTION_SELECTED = "action_selected"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    VERIFY = "verify"
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    FAILED = "failed"
