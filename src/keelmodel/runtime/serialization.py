from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from keelmodel.runtime.errors import ValidationError
from keelmodel.schema import FieldDefinition

_ALLOWED_URL_SCHEMES = {"http", "https"}


def serialize_value(field: FieldDefinition, value: Any) -> Any:
    if value is None:
        return None
    if field.type == "uuid":
        return str(value) if isinstance(value, UUID) else value
    if field.type == "date" and isinstance(value, date):
        return value.isoformat()
    if field.type == "datetime" and isinstance(value, datetime):
        return value.isoformat()
    return value


def deserialize_value(field: FieldDefinition, value: Any) -> Any:
    if value is None:
        return None
    match field.type:
        case "uuid":
            if isinstance(value, UUID):
                return value
            try:
                return UUID(str(value))
            except ValueError as exc:
                raise ValidationError(f"invalid UUID for field {field.name!r}") from exc
        case "integer":
            if isinstance(value, bool):
                raise ValidationError(f"invalid integer for field {field.name!r}")
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.strip().lstrip("+-").isdigit():
                return int(value)
            raise ValidationError(
                f"invalid integer {value!r} for field {field.name!r} "
                "(floats and non-digit strings are rejected)"
            )
        case "decimal":
            if isinstance(value, bool):
                raise ValidationError(f"invalid decimal for field {field.name!r}")
            try:
                return Decimal(str(value))
            except InvalidOperation as exc:
                raise ValidationError(f"invalid decimal for field {field.name!r}") from exc
        case "boolean":
            if isinstance(value, bool):
                return value
            raise ValidationError(
                f"invalid boolean {value!r} for field {field.name!r}: "
                "must be true/false, not a coercible value"
            )
        case "date":
            if isinstance(value, datetime):
                raise ValidationError(f"invalid date for field {field.name!r}")
            if isinstance(value, date):
                return value
            try:
                return date.fromisoformat(str(value))
            except ValueError as exc:
                raise ValidationError(f"invalid date for field {field.name!r}") from exc
        case "datetime":
            dt = value if isinstance(value, datetime) else _parse_datetime(value, field)
            if dt.tzinfo is None:
                raise ValidationError(
                    f"naive datetime for field {field.name!r}: "
                    "timezone-aware values are required"
                )
            return dt
        case "bytes":
            if isinstance(value, bytes):
                return value
            raise ValidationError(f"invalid bytes for field {field.name!r}")
        case "url":
            if not isinstance(value, str):
                raise ValidationError(f"invalid URL for field {field.name!r}")
            parsed = urlparse(value)
            if parsed.scheme not in _ALLOWED_URL_SCHEMES or not parsed.netloc:
                raise ValidationError(
                    f"invalid URL {value!r} for field {field.name!r}: "
                    f"scheme must be one of {sorted(_ALLOWED_URL_SCHEMES)} with a host"
                )
            return value
        case "text" | "enum":
            if not isinstance(value, str):
                raise ValidationError(f"invalid text for field {field.name!r}")
            if field.type == "enum" and value not in field.values:
                raise ValidationError(
                    f"invalid enum value {value!r} for field {field.name!r}"
                )
            return value
        case _:
            return value


def _parse_datetime(value: Any, field: FieldDefinition) -> datetime:
    if not isinstance(value, str):
        raise ValidationError(f"invalid datetime for field {field.name!r}")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"invalid datetime for field {field.name!r}") from exc


def coerce_input_values(definition: Any, values: dict[str, Any]) -> dict[str, Any]:
    fields = {field.name: field for field in definition.fields}
    unknown = set(values) - set(fields)
    if unknown:
        raise ValidationError(f"unknown field(s): {sorted(unknown)}")
    return {
        name: deserialize_value(fields[name], value) for name, value in values.items()
    }
