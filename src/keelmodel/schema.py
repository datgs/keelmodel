from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml
from packaging.version import Version


class SchemaError(ValueError):
    pass


@dataclass(frozen=True)
class FieldDefinition:
    name: str
    type: str
    required: bool = False
    primary_key: bool = False
    default: Any = None
    values: tuple[str, ...] = ()
    storage: str | None = None
    length: int | None = None


@dataclass(frozen=True)
class RelationDefinition:
    name: str
    kind: str
    target: str
    required: bool = False
    on_delete: str = "restrict"
    mapped_by: str | None = None


@dataclass(frozen=True)
class ModelDefinition:
    module: str
    name: str
    table: str
    fields: tuple[FieldDefinition, ...]
    checks: tuple[dict[str, Any], ...] = ()
    uniques: tuple[tuple[str, ...], ...] = ()
    indexes: tuple[tuple[str, ...], ...] = ()
    relations: tuple[RelationDefinition, ...] = ()
    source: Path | None = None

    @property
    def primary_key_fields(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields if field.primary_key)

    @property
    def resource(self) -> str:
        return f"{self.module}.{self.name}"


@dataclass(frozen=True)
class ModuleDependency:
    name: str
    version: str


@dataclass(frozen=True)
class ModuleDefinition:
    name: str
    version: Version
    requires: tuple[ModuleDependency, ...]
    exports: tuple[str, ...]
    models_path: str
    source: Path | None = None


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(
    loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict:
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise SchemaError(f"duplicate YAML key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


_FIELD_TYPES = {
    "uuid",
    "text",
    "integer",
    "decimal",
    "boolean",
    "date",
    "datetime",
    "bytes",
    "enum",
    "json",
    "url",
    "file_reference",
    "location",
}
_FIELD_KEYS = {"type", "required", "primary_key", "default", "values", "storage", "length"}

_MIXINS: dict[str, tuple[FieldDefinition, ...]] = {
    "uuid_pk": (FieldDefinition("id", "uuid", True, True, "uuid4"),),
    "timestamps": (
        FieldDefinition("created_at", "datetime", True, False, "current_timestamp"),
        FieldDefinition("updated_at", "datetime", True, False, "current_timestamp"),
    ),
}


def _apply_mixins(
    mixins: list[str], fields: list[FieldDefinition], location: str
) -> list[FieldDefinition]:
    if not mixins:
        return fields
    merged = list(fields)
    names = {f.name for f in merged}
    for mixin_name in mixins:
        for field in _MIXINS[mixin_name]:
            if field.name in names:
                raise SchemaError(
                    f"{location}: mixin {mixin_name!r} field {field.name!r} already defined"
                )
            merged.append(field)
            names.add(field.name)
    return merged


def _field_groups(
    raw: Any, kind: str, field_names: set[str], location: str
) -> list[tuple[str, ...]]:
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise SchemaError(f"{location}: constraints.{kind} must be a list")
    groups = []
    for item in raw:
        members = item if isinstance(item, list) else [item]
        if not members or not all(isinstance(m, str) for m in members):
            raise SchemaError(
                f"{location}: constraints.{kind} entries must be field names"
            )
        missing = [m for m in members if m not in field_names]
        if missing:
            raise SchemaError(
                f"{location}: constraints.{kind} references unknown field(s) {missing}"
            )
        groups.append(tuple(members))
    return groups


def load_model(path: str | Path) -> ModelDefinition:
    source = Path(path)
    try:
        raw = yaml.load(source.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except (OSError, yaml.YAMLError, SchemaError) as exc:
        raise SchemaError(f"{source}: {exc}") from exc
    return parse_model(raw, source=source)


def parse_model(raw: Any, *, source: Path | None = None) -> ModelDefinition:
    location = str(source) if source else "<model>"
    if not isinstance(raw, dict):
        raise SchemaError(f"{location}: model root must be a mapping")
    _keys(
        raw,
        {
            "version",
            "module",
            "model",
            "table",
            "fields",
            "constraints",
            "relations",
            "mixins",
        },
        location,
    )
    if raw.get("version") != 1:
        raise SchemaError(f"{location}: version must be 1")

    module = _identifier(raw.get("module"), "module", location)
    name = _identifier(raw.get("model"), "model", location, upper=True)
    table = raw.get("table", f"{module}_{_snake_case(name)}")
    table = _identifier(table, "table", location)

    raw_fields = raw.get("fields", {})
    if not isinstance(raw_fields, dict):
        raise SchemaError(f"{location}: fields must be a mapping")

    fields = []
    primary_keys = 0
    for field_name, spec in raw_fields.items():
        field_name = _identifier(field_name, "field name", location)
        if not isinstance(spec, dict):
            raise SchemaError(f"{location}: field {field_name!r} must be a mapping")
        _keys(spec, _FIELD_KEYS, f"{location}: field {field_name}")
        kind = spec.get("type")
        if kind not in _FIELD_TYPES:
            raise SchemaError(f"{location}: field {field_name!r} has unsupported type {kind!r}")
        required = _boolean(spec.get("required", False), "required", location, field_name)
        primary_key = _boolean(spec.get("primary_key", False), "primary_key", location, field_name)
        if primary_key:
            primary_keys += 1
            required = True
        values = spec.get("values", ())
        if kind == "enum":
            valid_values = isinstance(values, list) and all(
                isinstance(value, str) for value in values
            )
            if not valid_values or not values:
                raise SchemaError(
                    f"{location}: enum field {field_name!r} requires non-empty string values"
                )
            if len(set(values)) != len(values):
                raise SchemaError(f"{location}: enum field {field_name!r} has duplicate values")
            values = tuple(values)
        elif "values" in spec:
            raise SchemaError(f"{location}: values is only valid for enum fields")

        storage = spec.get("storage")
        if kind == "enum" and storage not in (None, "text"):
            raise SchemaError(f"{location}: enum field {field_name!r} storage must be text")
        if kind in {"file_reference", "location"} and storage not in (None, "jsonb"):
            raise SchemaError(f"{location}: {kind} field {field_name!r} storage must be jsonb")
        if kind not in {"enum", "file_reference", "location"} and storage is not None:
            raise SchemaError(f"{location}: storage is not configurable for {kind} fields")

        default = spec.get("default")
        _validate_default(kind, default, location, field_name, values)
        length = spec.get("length")
        if length is not None:
            if kind not in {"text", "url", "enum"}:
                raise SchemaError(
                    f"{location}: length is only valid for text/url/enum fields"
                )
            if not isinstance(length, int) or isinstance(length, bool) or length <= 0:
                raise SchemaError(
                    f"{location}: field {field_name!r} length must be a positive int"
                )
        fields.append(
            FieldDefinition(
                field_name, kind, required, primary_key, default, values, storage, length
            )
        )

    constraints = raw.get("constraints", {})
    if not isinstance(constraints, dict):
        raise SchemaError(f"{location}: constraints must be a mapping")
    _keys(constraints, {"check", "unique", "index"}, f"{location}: constraints")

    relations_raw = raw.get("relations", {})
    if not isinstance(relations_raw, dict):
        raise SchemaError(f"{location}: relations must be a mapping")
    field_names = {field.name for field in fields}
    relations = []
    for rel_name, rel_spec in relations_raw.items():
        rel_name = _identifier(rel_name, "relation name", location)
        if rel_name in field_names:
            raise SchemaError(f"{location}: relation {rel_name!r} conflicts with a field name")
        if not isinstance(rel_spec, dict):
            raise SchemaError(f"{location}: relation {rel_name!r} must be a mapping")
        _keys(
            rel_spec,
            {"type", "target", "required", "on_delete", "mapped_by"},
            f"{location}: relation {rel_name}",
        )
        rel_kind = rel_spec.get("type")
        if rel_kind not in {"many_to_one", "one_to_one", "one_to_many"}:
            raise SchemaError(
                f"{location}: relation {rel_name!r} has unsupported type {rel_kind!r}"
            )
        target = rel_spec.get("target")
        if not isinstance(target, str) or "." not in target:
            raise SchemaError(
                f"{location}: relation {rel_name!r} target must be '<module>.<Model>'"
            )
        target_module, target_model = target.split(".", 1)
        _identifier(target_module, "relation target module", location)
        _identifier(target_model, "relation target model", location, upper=True)
        rel_required = _boolean(
            rel_spec.get("required", False), "required", location, rel_name
        )
        on_delete = rel_spec.get("on_delete", "restrict")
        if on_delete not in {"restrict", "cascade", "set_null"}:
            raise SchemaError(
                f"{location}: relation {rel_name!r} on_delete must be restrict/cascade/set_null"
            )
        if rel_kind == "one_to_many" and on_delete != "restrict":
            raise SchemaError(
                f"{location}: one_to_many relation {rel_name!r} does not own on_delete"
            )
        mapped_by = rel_spec.get("mapped_by")
        if rel_kind == "one_to_many":
            if mapped_by is None:
                raise SchemaError(
                    f"{location}: one_to_many relation {rel_name!r} requires mapped_by"
                )
            _identifier(mapped_by, "mapped_by", location)
        elif mapped_by is not None:
            raise SchemaError(
                f"{location}: mapped_by is only valid on one_to_many relations"
            )
        relations.append(
            RelationDefinition(
                rel_name, rel_kind, target, rel_required, on_delete, mapped_by
            )
        )

    fk_names = {
        f"{rel.name}_id" for rel in relations if rel.kind != "one_to_many"
    }
    constraint_names = {field.name for field in fields} | fk_names
    uniques = _field_groups(
        constraints.get("unique", []), "unique", constraint_names, location
    )
    indexes = _field_groups(
        constraints.get("index", []), "index", constraint_names, location
    )
    checks = constraints.get("check", [])
    if not isinstance(checks, list) or not all(isinstance(check, dict) for check in checks):
        raise SchemaError(f"{location}: constraints.check must be a list of expressions")
    from keelmodel.runtime.constraints import validate_check_constraints

    try:
        validate_check_constraints(checks, constraint_names)
    except ValueError as exc:
        raise SchemaError(f"{location}: invalid check constraint: {exc}") from exc

    mixins_raw = raw.get("mixins", [])
    if not isinstance(mixins_raw, list) or not all(isinstance(m, str) for m in mixins_raw):
        raise SchemaError(f"{location}: mixins must be a list of mixin names")
    unknown_mixins = set(mixins_raw) - set(_MIXINS)
    if unknown_mixins:
        raise SchemaError(f"{location}: unknown mixin(s) {sorted(unknown_mixins)}")
    fields = _apply_mixins(mixins_raw, fields, location)
    if not fields or not any(field.primary_key for field in fields):
        raise SchemaError(f"{location}: at least one primary_key field is required")

    return ModelDefinition(
        module,
        name,
        table,
        tuple(fields),
        tuple(checks),
        tuple(uniques),
        tuple(indexes),
        tuple(relations),
        source,
    )


def _validate_default(
    kind: str, value: Any, location: str, field_name: str, enum_values: tuple[str, ...]
) -> None:
    if value is None:
        return
    valid = {
        "uuid": isinstance(value, str) and (_is_uuid(value) or value == "uuid4"),
        "text": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "decimal": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "date": isinstance(value, (str, date)) and not isinstance(value, datetime),
        "datetime": isinstance(value, (str, datetime)),
        "bytes": isinstance(value, str),
        "enum": isinstance(value, str) and value in enum_values,
        "json": isinstance(value, (dict, list, str, int, float, bool)),
        "url": isinstance(value, str),
        "file_reference": isinstance(value, dict),
        "location": isinstance(value, dict),
    }[kind]
    if not valid:
        raise SchemaError(
            f"{location}: default for field {field_name!r} does not match type {kind!r}"
        )


def _is_uuid(value: str) -> bool:
    from uuid import UUID

    try:
        UUID(value)
        return True
    except ValueError:
        return False


def _keys(mapping: dict, allowed: set[str], location: str) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        names = ", ".join(sorted(map(str, unknown)))
        raise SchemaError(f"{location}: unknown key(s): {names}")


def _identifier(value: Any, label: str, location: str, *, upper: bool = False) -> str:
    if not isinstance(value, str) or not value.isidentifier() or value.startswith("_"):
        raise SchemaError(f"{location}: {label} must be a public Python-style identifier")
    if upper and not value[0].isupper():
        raise SchemaError(f"{location}: {label} must start with an uppercase letter")
    return value


def _boolean(value: Any, label: str, location: str, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise SchemaError(f"{location}: field {field_name!r} {label} must be a boolean")
    return value


def _snake_case(value: str) -> str:
    result = []
    for index, char in enumerate(value):
        if char.isupper() and index:
            result.append("_")
        result.append(char.lower())
    return "".join(result)
