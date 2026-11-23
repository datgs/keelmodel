from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class PolicyError(ValueError):
    pass


def load_policy(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PolicyError(f"{source}: {exc}") from exc
    return parse_policy(raw)


def parse_policy(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        raise PolicyError("policy root must be a mapping")
    if raw.get("version") != 1:
        raise PolicyError("policy version must be 1")
    statements = raw.get("statements")
    if not isinstance(statements, list) or not statements:
        raise PolicyError("statements must be a non-empty list")
    for i, stmt in enumerate(statements):
        _validate_statement(stmt, i)
    return statements


def _validate_statement(stmt: Any, index: int) -> None:
    if not isinstance(stmt, dict):
        raise PolicyError(f"statement {index}: must be a mapping")
    required = {"effect", "actions", "resources", "subjects"}
    missing = required - set(stmt)
    if missing:
        raise PolicyError(f"statement {index}: missing {sorted(missing)}")
    if stmt["effect"] not in ("allow", "deny"):
        raise PolicyError(f"statement {index}: effect must be allow or deny")
    for key in ("actions", "resources", "subjects"):
        val = stmt[key]
        if not isinstance(val, list) or not val or not all(isinstance(v, str) for v in val):
            raise PolicyError(f"statement {index}: {key} must be a non-empty string list")
