from __future__ import annotations

from typing import Any

from sqlalchemy import CheckConstraint, and_, column, or_

from keelmodel.schema import ModelDefinition

_SUPPORTED_OPERATORS = {"eq", "ne", "lt", "lte", "gt", "gte"}


def validate_check_constraints(checks: list[dict[str, Any]], fields: set[str]) -> None:
    for check in checks:
        _compile_group(check, fields)


def compile_check_constraints(model: ModelDefinition) -> tuple[Any, ...]:
    field_names = {field.name for field in model.fields} | {
        f"{rel.name}_id" for rel in model.relations if rel.kind != "one_to_many"
    }
    return tuple(
        CheckConstraint(_compile_group(group, field_names)) for group in model.checks
    )


def _compile_group(group: dict[str, Any], fields: set[str]) -> Any:
    if set(group) == {"all"}:
        return _join_group(group["all"], fields, "and")
    if set(group) == {"any"}:
        return _join_group(group["any"], fields, "or")
    if set(group) == {"field", "is_null"}:
        col = column(_field(group["field"], fields))
        if not isinstance(group["is_null"], bool):
            raise ValueError("is_null must be a boolean")
        return col.is_(None) if group["is_null"] else col.is_not(None)
    if set(group) == {"field", "op", "value"}:
        col = column(_field(group["field"], fields))
        return _comparison(col, group["op"], group["value"])
    raise ValueError(f"invalid check expression shape: {sorted(group)}")


def _join_group(items: Any, fields: set[str], operator: str) -> Any:
    if not isinstance(items, list) or not items:
        raise ValueError(f"{operator} check group must be a non-empty list")
    compiled = [_compile_group(item, fields) for item in items]
    return and_(*compiled) if operator == "and" else or_(*compiled)


def _comparison(col: Any, operation: Any, value: Any) -> Any:
    if value is None:
        raise ValueError("null comparisons must use is_null")
    if not isinstance(value, (str, int, float, bool)):
        raise ValueError(f"unsupported check literal {value!r}")
    if operation == "eq":
        return col == value
    if operation == "ne":
        return col != value
    if operation == "lt":
        return col < value
    if operation == "lte":
        return col <= value
    if operation == "gt":
        return col > value
    if operation == "gte":
        return col >= value
    raise ValueError(f"unsupported check operator {operation!r}")


def _field(value: Any, fields: set[str]) -> str:
    if not isinstance(value, str) or value not in fields:
        raise ValueError(f"unknown check field {value!r}")
    return value
