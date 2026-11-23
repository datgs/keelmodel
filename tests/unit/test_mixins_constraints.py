import pytest

from keelmodel.runtime.models import map_model
from keelmodel.schema import SchemaError, parse_model


def test_uuid_pk_mixin_provides_primary_key():
    model = parse_model(
        {
            "version": 1,
            "module": "sales",
            "model": "Note",
            "mixins": ["uuid_pk"],
            "fields": {"body": {"type": "text"}},
        }
    )
    names = {f.name for f in model.fields}
    assert {"id", "body"} <= names
    pk = [f for f in model.fields if f.primary_key]
    assert len(pk) == 1 and pk[0].name == "id" and pk[0].default == "uuid4"


def test_timestamps_mixin_adds_datetime_fields():
    model = parse_model(
        {
            "version": 1,
            "module": "sales",
            "model": "Note",
            "mixins": ["timestamps"],
            "fields": {"id": {"type": "uuid", "primary_key": True}},
        }
    )
    names = {f.name: f for f in model.fields}
    assert names["created_at"].type == "datetime"
    assert names["created_at"].default == "current_timestamp"
    assert names["updated_at"].type == "datetime"


def test_mixin_conflict_rejected():
    with pytest.raises(SchemaError, match="already defined"):
        parse_model(
            {
                "version": 1,
                "module": "sales",
                "model": "Note",
                "mixins": ["uuid_pk"],
                "fields": {"id": {"type": "uuid", "primary_key": True}},
            }
        )


def test_unknown_mixin_rejected():
    with pytest.raises(SchemaError, match="unknown mixin"):
        parse_model(
            {
                "version": 1,
                "module": "sales",
                "model": "Note",
                "mixins": ["magic"],
                "fields": {"id": {"type": "uuid", "primary_key": True}},
            }
        )


def test_unique_and_index_constraints_map_to_ddl():
    model = parse_model(
        {
            "version": 1,
            "module": "sales",
            "model": "Note",
            "table": "sales_note_uniq",
            "fields": {
                "id": {"type": "uuid", "primary_key": True},
                "slug": {"type": "text", "required": True},
                "body": {"type": "text"},
            },
            "constraints": {
                "unique": [["slug"]],
                "index": [["body", "slug"]],
            },
        }
    )
    mapped = map_model(model)
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable

    ddl = str(CreateTable(mapped.__table__).compile(dialect=postgresql.dialect()))
    assert 'UNIQUE ("slug")' in ddl or 'UNIQUE (slug)' in ddl
    index_names = [idx.name for idx in mapped.__table__.indexes]
    assert "sales_note_uniq_body_slug_idx" in index_names


def test_unique_unknown_field_rejected():
    with pytest.raises(SchemaError, match="unknown field"):
        parse_model(
            {
                "version": 1,
                "module": "sales",
                "model": "Note",
                "fields": {"id": {"type": "uuid", "primary_key": True}},
                "constraints": {"unique": [["missing"]]},
            }
        )
