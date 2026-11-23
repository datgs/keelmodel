from __future__ import annotations

import keyword
from pathlib import Path

from keelmodel.schema import ModelDefinition, SchemaError, load_model

_PYTHON_TYPES = {
    "uuid": "UUID",
    "text": "str",
    "integer": "int",
    "decimal": "Decimal",
    "boolean": "bool",
    "date": "date",
    "datetime": "datetime",
    "bytes": "bytes",
    "enum": "str",
    "json": "dict[str, object]",
    "url": "str",
    "file_reference": "dict[str, object]",
    "location": "dict[str, object]",
}


def render_model(model: ModelDefinition) -> str:
    if any(keyword.iskeyword(field.name) for field in model.fields):
        raise SchemaError(f"{model.resource}: field names must not be Python keywords")

    imports = ["from __future__ import annotations"]
    stdlib = []
    kinds = {field.type for field in model.fields}
    if kinds & {"date", "datetime"}:
        names = []
        if "date" in kinds:
            names.append("date")
        if "datetime" in kinds:
            names.append("datetime")
        stdlib.append(f"from datetime import {', '.join(names)}")
    if "decimal" in kinds:
        stdlib.append("from decimal import Decimal")
    if "uuid" in kinds:
        stdlib.append("from uuid import UUID")
    if stdlib:
        imports.append("")
        imports.extend(stdlib)

    lines = imports + [
        "",
        "",
        f"class {model.name}:",
        f'    __tablename__ = "{model.table}"',
        f'    __resource__ = "{model.resource}"',
        "",
    ]
    for field in model.fields:
        annotation = _PYTHON_TYPES[field.type]
        if not field.required and not field.primary_key:
            annotation = f"{annotation} | None"
        lines.append(f"    {field.name}: {annotation}")
    lines.extend(["", "    __fields__ = ("])
    lines.extend(f'        "{field.name}",' for field in model.fields)
    lines.extend(["    )", ""])
    return "\n".join(lines)


def generate_model(source: str | Path, output: str | Path) -> Path:
    model = load_model(source)
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f"{_snake_case(model.name)}.py"
    target.write_text(render_model(model), encoding="utf-8")
    return target


def _snake_case(value: str) -> str:
    result = []
    for index, char in enumerate(value):
        if char.isupper() and index:
            result.append("_")
        result.append(char.lower())
    return "".join(result)
