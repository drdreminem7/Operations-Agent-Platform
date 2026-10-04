from dataclasses import dataclass


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    output: dict[str, object]
