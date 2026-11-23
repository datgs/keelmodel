from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OperationContext:
    subject: dict[str, Any]
    attributes: dict[str, Any]
