from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Operation(StrEnum):
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    QUERY = "query"
    BULK = "bulk"


@dataclass(frozen=True)
class OperationRequest:
    operation: Operation
    resource: str
    data: dict[str, Any] | None = None
    key: Any = None
