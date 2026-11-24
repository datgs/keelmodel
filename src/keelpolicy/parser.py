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
    if "condition" in stmt:
        _validate_condition(stmt["condition"], f"statement {index}")
    if "fields" in stmt:
        fields = stmt["fields"]
        if not isinstance(fields, dict) or not fields:
            raise PolicyError(f"statement {index}: fields must be a non-empty mapping")
        for name, spec in fields.items():
            if not isinstance(name, str):
                raise PolicyError(f"statement {index}: field names must be strings")
            if isinstance(spec, bool):
                continue
            if isinstance(spec, dict) and spec and set(spec) <= {
                "read", "write", "filter", "order"
            } and all(isinstance(v, bool) for v in spec.values()):
                continue
            raise PolicyError(
                f"statement {index}: fields[{name!r}] must be a boolean or "
                "a mapping of read/write/filter/order booleans"
            )


_OPS = {"eq", "ne", "in", "contains", "lt", "lte", "gt", "gte", "is_null"}


def _validate_condition(cond: Any, where: str) -> None:
    if not isinstance(cond, dict) or not cond:
        raise PolicyError(f"{where}: condition must be a non-empty mapping")
    keys = set(cond)
    if keys == {"all"} or keys == {"any"}:
        name = next(iter(keys))
        children = cond[name]
        if not isinstance(children, list) or not children:
            raise PolicyError(f"{where}: '{name}' must be a non-empty list")
        for child in children:
            _validate_condition(child, where)
        return
    if keys == {"field", "op", "value"}:
        field, op, value = cond["field"], cond["op"], cond["value"]
        if not isinstance(field, str) or "." not in field:
            raise PolicyError(
                f"{where}: condition field must be 'record.x', "
                "'subject.x', or 'attributes.x'"
            )
        prefix = field.split(".", 1)[0]
        if prefix not in {"record", "subject", "attributes"}:
            raise PolicyError(
                f"{where}: condition field must be 'record.x', "
                "'subject.x', or 'attributes.x'"
            )
        if op not in _OPS:
            raise PolicyError(f"{where}: unknown op {op!r}; allowed: {sorted(_OPS)}")
        if op == "in" and not isinstance(value, list):
            raise PolicyError(f"{where}: 'in' requires a list value")
        if op == "is_null" and not isinstance(value, bool):
            raise PolicyError(f"{where}: 'is_null' requires a boolean value")
        return
    raise PolicyError(
        f"{where}: condition must be {{'all': [...]}}, {{'any': [...]}}, "
        "or {'field', 'op', 'value'}"
    )
