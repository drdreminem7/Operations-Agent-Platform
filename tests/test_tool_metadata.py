from dataclasses import FrozenInstanceError

import pytest

from app.tools.defaults import create_default_registry
from app.tools.metadata import RetryClass, ToolMetadata


def test_tool_metadata_accepts_valid_values() -> None:
    metadata = ToolMetadata(
        name="get_service_health",
        description="Read health for a service",
        read_only=True,
        required_permissions=frozenset({"service:read"}),
        timeout_seconds=2,
    )

    assert metadata.name == "get_service_health"
    assert metadata.read_only is True
    assert metadata.required_permissions == frozenset({"service:read"})


def test_tool_metadata_rejects_empty_name() -> None:
    with pytest.raises(ValueError, match="name cannot be empty"):
        ToolMetadata(name="", description="A tool", read_only=True)


def test_tool_metadata_rejects_nonpositive_timeout() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        ToolMetadata(
            name="slow_tool", description="A tool", read_only=True, timeout_seconds=0
        )


def test_tool_metadata_is_immutable() -> None:
    metadata = ToolMetadata(
        name="get_service_health",
        description="Read health for a service",
        read_only=True,
    )

    attribute = "name"
    with pytest.raises(FrozenInstanceError):
        setattr(metadata, attribute, "renamed")


def test_default_tools_have_explicit_retry_classes() -> None:
    metadata = {tool.name: tool for tool in create_default_registry().list_tools()}

    assert {
        name: tool.retry_class for name, tool in metadata.items()
    } == {
        "get_service_health": RetryClass.READ_ONLY_IDEMPOTENT,
        "search_logs": RetryClass.READ_ONLY_IDEMPOTENT,
        "get_recent_deployments": RetryClass.READ_ONLY_IDEMPOTENT,
        "restart_service": RetryClass.WRITE_NON_IDEMPOTENT,
        "rollback_deployment": RetryClass.WRITE_NON_IDEMPOTENT,
    }


def test_custom_tool_defaults_to_no_retry() -> None:
    metadata = ToolMetadata(name="custom", description="Custom tool", read_only=False)

    assert metadata.retry_class == RetryClass.NO_RETRY


@pytest.mark.parametrize(
    ("read_only", "retry_class"),
    [
        (True, RetryClass.WRITE_IDEMPOTENT),
        (True, RetryClass.WRITE_NON_IDEMPOTENT),
        (False, RetryClass.READ_ONLY_IDEMPOTENT),
    ],
)
def test_retry_class_must_match_tool_effect(
    read_only: bool, retry_class: RetryClass
) -> None:
    with pytest.raises(ValueError, match="retry class"):
        ToolMetadata(
            name="mismatch",
            description="Invalid retry classification",
            read_only=read_only,
            retry_class=retry_class,
        )
