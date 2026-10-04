import pytest
from pydantic import ValidationError

from app.agent.decision_provider import ActionProposal, ToolRequest


def test_tool_request_accepts_valid_decision() -> None:
    request = ToolRequest.model_validate(
        {
            "tool_name": "search_logs",
            "arguments": {"service": "checkout", "query": "error"},
            "reason": "Search for recent errors.",
        }
    )

    assert request.tool_name == "search_logs"
    assert request.arguments["service"] == "checkout"


def test_tool_request_rejects_unexpected_fields() -> None:
    with pytest.raises(ValidationError):
        ToolRequest.model_validate(
            {
                "tool_name": "search_logs",
                "arguments": {},
                "reason": "Search logs.",
                "permission": "admin",
            }
        )


def test_action_proposal_rejects_empty_action() -> None:
    with pytest.raises(ValidationError):
        ActionProposal.model_validate(
            {
                "action": "",
                "arguments": {"service": "checkout"},
                "reason": "Propose an action.",
            }
        )


def test_action_proposal_rejects_overlong_reason() -> None:
    with pytest.raises(ValidationError):
        ActionProposal.model_validate(
            {
                "action": "rollback_deployment",
                "arguments": {"service": "checkout", "version": "2.4.1"},
                "reason": "x" * 501,
            }
        )


def test_action_proposal_rejects_model_supplied_approval_requirement() -> None:
    with pytest.raises(ValidationError):
        ActionProposal.model_validate(
            {
                "action": "rollback_deployment",
                "arguments": {"service": "checkout", "version": "2.4.1"},
                "reason": "Rollback the deployment.",
                "requires_approval": False,
            }
        )


def test_tool_request_rejects_unknown_tool() -> None:
    with pytest.raises(ValidationError):
        ToolRequest.model_validate(
            {
                "tool_name": "run_shell",
                "arguments": {},
                "reason": "Run a command.",
            }
        )


def test_tool_request_rejects_impossible_arguments() -> None:
    with pytest.raises(ValidationError):
        ToolRequest.model_validate(
            {
                "tool_name": "get_recent_deployments",
                "arguments": {"service": "checkout", "limit": 0},
                "reason": "Inspect deployments.",
            }
        )


def test_action_proposal_rejects_unknown_action() -> None:
    with pytest.raises(ValidationError):
        ActionProposal.model_validate(
            {
                "action": "delete_database",
                "arguments": {},
                "reason": "Delete data.",
            }
        )
