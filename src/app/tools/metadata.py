from dataclasses import dataclass
from enum import StrEnum


class RetryClass(StrEnum):
    READ_ONLY_IDEMPOTENT = "read_only_idempotent"
    WRITE_IDEMPOTENT = "write_idempotent"
    WRITE_NON_IDEMPOTENT = "write_non_idempotent"
    NO_RETRY = "no_retry"


@dataclass(frozen=True)
class ToolMetadata:
    name: str
    description: str
    read_only: bool
    required_permissions: frozenset[str] = frozenset()
    timeout_seconds: float = 5.0
    retry_class: RetryClass = RetryClass.NO_RETRY

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Tool name cannot be empty")
        if not self.description.strip():
            raise ValueError("Tool description cannot be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("Tool timeout must be greater than zero")
        if self.read_only and self.retry_class in {
            RetryClass.WRITE_IDEMPOTENT,
            RetryClass.WRITE_NON_IDEMPOTENT,
        }:
            raise ValueError("Read-only tools cannot have a write retry class")
        if not self.read_only and self.retry_class == RetryClass.READ_ONLY_IDEMPOTENT:
            raise ValueError("Write tools cannot have a read-only retry class")
