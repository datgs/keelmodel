from pathlib import Path

import pytest

from keelmodel.schema import SchemaError, parse_model


def test_parse_model_defaults_table_name_and_primary_key():
    model = parse_model(
        {
            "version": 1,
            "module": "sales",
            "model": "Invoice",
            "fields": {
                "id": {"type": "uuid", "primary_key": True},
                "total": {"type": "decimal", "required": True},
            },
        }
    )

    assert model.resource == "sales.Invoice"
    assert model.table == "sales_invoice"
    assert model.fields[0].required is True


def test_reject_unknown_model_key():
    with pytest.raises(SchemaError, match="unknown key"):
        parse_model(
            {
                "version": 1,
                "module": "sales",
                "model": "Invoice",
                "typo": True,
                "fields": {"id": {"type": "uuid", "primary_key": True}},
            }
        )


def test_reject_duplicate_yaml_keys(tmp_path: Path):
    path = tmp_path / "invoice.yaml"
    path.write_text(
        "\n".join(
            [
                "version: 1",
                "module: sales",
                "model: Invoice",
                "fields:",
                "  id:",
                "    type: uuid",
                "    primary_key: true",
                "  id:",
                "    type: text",
            ]
        ),
        encoding="utf-8",
    )
    from keelmodel.schema import load_model

    with pytest.raises(SchemaError, match="duplicate YAML key"):
        load_model(path)


def test_reject_model_without_primary_key():
    with pytest.raises(SchemaError, match="primary_key"):
        parse_model(
            {
                "version": 1,
                "module": "sales",
                "model": "Invoice",
                "fields": {"name": {"type": "text"}},
            }
        )


def test_reject_check_constraint_with_unknown_field_or_operator():
    base = {
        "version": 1,
        "module": "sales",
        "model": "Invoice",
        "fields": {"id": {"type": "uuid", "primary_key": True}},
    }
    with pytest.raises(SchemaError, match="unknown check field"):
        parse_model(
            {
                **base,
                "constraints": {"check": [{"field": "missing", "op": "eq", "value": 1}]},
            }
        )
    with pytest.raises(SchemaError, match="unsupported check operator"):
        parse_model(
            {
                **base,
                "constraints": {"check": [{"field": "id", "op": "matches", "value": "x"}]},
            }
        )
