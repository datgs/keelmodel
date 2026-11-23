from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from keelmodel.runtime.errors import ValidationError
from keelmodel.schema import FieldDefinition


def serialize_value(field: FieldDefinition, value: Any) -> Any:
    if value is None:
        return None
    if field.type == "uuid":
        return str(value) if isinstance(value, UUID) else value
    if field.type == "decimal":
        return value
    if field.type == "date":
        return value.isoformat() if isinstance(value, date) else value
    if field.type == "datetime":
        return value.isoformat() if isinstance(value, datetime) else value
    if field.type == "bytes":
        return value
    return value


def deserialize_value(field: FieldDefinition, value: Any) -> Any:
    if value is None:
        return None
    if field.type == "uuid":
        try:
            return UUID(str(value))
        except ValueError as exc:
            raise ValidationError(f"invalid UUID value for field {field.name!r}") from exc
    if field.type == "integer":
        try:
            return int(value)
        except (ValueError, TypeError) as exc:
            raise ValidationError(f"invalid integer value for field {field.name!r}") from exc
    if field.type == "decimal":
        try:
            return Decimal(str(value))
        except (ValueError, ArithmeticError) as exc:
            raise ValidationError(f"invalid decimal value for field {field.name!r}") from exc
    if field.type == "boolean":
        return bool(value)
    if field.type == "date":
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value))
        except ValueError as exc:
            raise ValidationError(f"invalid date value for field {field.name!r}") from exc
    if field.type == "datetime":
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except ValueError as exc:
            raise ValidationError(f"invalid datetime value for field {field.name!r}") from exc
    if field.type == "bytes":
        if isinstance(value, bytes):
            return value
        try:
            return bytes.fromhex(str(value))
        except ValueError as exc:
            raise ValidationError(f"invalid bytes value for field {field.name!r}") from exc
    return value


def coerce_input_values(definition: Any, values: dict[str, Any]) -> dict[str, Any]:
    fields = {field.name: field for field in definition.fields}
    unknown = set(values) - set(fields)
    if unknown:
        raise ValidationError(f"unknown field(s): {sorted(unknown)}")
    result = {}
    for name, value in values.items():
        result[name] = deserialize_value(fields[name], value)
    return result
