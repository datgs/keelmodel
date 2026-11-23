from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Page:
    items: tuple[Any, ...]
    total: int
    limit: int
    offset: int
