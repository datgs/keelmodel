from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Decision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True)
class PolicyRequest:
    action: str
    resource: str
    subject: dict[str, Any]
    attributes: dict[str, Any]
    record: dict[str, Any] | None = None


@dataclass(frozen=True)
class PolicyDecision:
    decision: Decision
    reason: str | None = None
    condition: dict[str, Any] | None = None
