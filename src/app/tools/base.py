from abc import ABC, abstractmethod

from .metadata import ToolMetadata
from .result import ToolResult


class Tool(ABC):
    def __init__(self, metadata: ToolMetadata) -> None:
        self._metadata = metadata

    @property
    def metadata(self) -> ToolMetadata:
        return self._metadata

    @abstractmethod
    def validate_input(
        self,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        """Validate and normalize input, or raise an error."""
        ...

    @abstractmethod
    async def execute(
        self,
        validated_input: dict[str, object],
    ) -> ToolResult:
        """Run the tool using already-validated input."""
        ...
