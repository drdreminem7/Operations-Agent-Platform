import asyncio

import pytest

from app.tools.errors import ToolExecutionError
from app.tools.search_logs import SearchLogsTool


def test_search_logs_tool_returns_matching_logs() -> None:
    tool = SearchLogsTool()
    validated_input = tool.validate_input({"service": "checkout", "query": "payment"})

    result = asyncio.run(tool.execute(validated_input))

    assert result.tool_name == "search_logs"
    assert result.output == {
        "service": "checkout",
        "query": "payment",
        "matches": [
            {
                "service": "checkout",
                "level": "error",
                "message": "Payment provider timed out",
            }
        ],
    }


def test_search_logs_tool_search_is_case_insensitive() -> None:
    tool = SearchLogsTool()
    validated_input = tool.validate_input({"service": "checkout", "query": "PAYMENT"})

    result = asyncio.run(tool.execute(validated_input))

    assert result.output["matches"] == [
        {
            "service": "checkout",
            "level": "error",
            "message": "Payment provider timed out",
        }
    ]


def test_search_logs_tool_returns_empty_matches_when_none_found() -> None:
    tool = SearchLogsTool()
    validated_input = tool.validate_input({"service": "checkout", "query": "database"})

    result = asyncio.run(tool.execute(validated_input))

    assert result.output["matches"] == []


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"query": "payment"},
        {"service": "checkout"},
        {"service": "", "query": "payment"},
        {"service": "checkout", "query": ""},
        {"service": 123, "query": "payment"},
        {"service": "checkout", "query": None},
    ],
)
def test_search_logs_tool_rejects_invalid_input(
    arguments: dict[str, object],
) -> None:
    tool = SearchLogsTool()

    with pytest.raises(ToolExecutionError):
        tool.validate_input(arguments)
