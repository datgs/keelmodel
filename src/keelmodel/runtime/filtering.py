from __future__ import annotations

from typing import Any


def compile_filter_expression(
    expression: dict[str, Any], model: Any, coercer: Any = None
) -> Any:
    return _compile_group(expression, model, coercer)


def _compile_group(expression: dict[str, Any], model: Any, coercer: Any) -> Any:
    if set(expression) == {"all"}:
        return _join(expression["all"], model, "and", coercer)
    if set(expression) == {"any"}:
        return _join(expression["any"], model, "or", coercer)
    if set(expression) == {"field", "op", "value"}:
        name = expression["field"]
        column = _column(name, model)
        operation = expression["op"]
        value = expression["value"]
        if coercer is not None:
            value = coercer(name, value)
        return _comparison(column, operation, value)
    if set(expression) == {"field", "is_null"}:
        column = _column(expression["field"], model)
        return column.is_(None) if expression["is_null"] else column.is_not(None)
    raise ValueError(f"invalid filter expression shape: {sorted(expression)}")


def _join(items: Any, model: Any, operator: str, coercer: Any) -> Any:
    if not isinstance(items, list) or not items:
        raise ValueError(f"{operator} filter group must be a non-empty list")
    compiled = [_compile_group(item, model, coercer) for item in items]
    if operator == "and":
        from sqlalchemy import and_

        return and_(*compiled)
    from sqlalchemy import or_

    return or_(*compiled)


def _column(name: Any, model: Any) -> Any:
    if not isinstance(name, str) or not hasattr(model, name):
        raise ValueError(f"unknown filter field {name!r}")
    return getattr(model, name)


def _comparison(column: Any, operation: Any, value: Any) -> Any:
    if operation == "eq":
        return column == value
    if operation == "ne":
        return column != value
    if operation == "lt":
        return column < value
    if operation == "lte":
        return column <= value
    if operation == "gt":
        return column > value
    if operation == "gte":
        return column >= value
    raise ValueError(f"unsupported filter operator {operation!r}")
