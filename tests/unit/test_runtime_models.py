from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from keelmodel.runtime.models import map_model
from keelmodel.schema import parse_model


def test_maps_model_fields_to_postgresql_table():
    definition = parse_model(
        {
            "version": 1,
            "module": "sales",
            "model": "Invoice",
            "table": "sales_invoice_rtm",
            "fields": {
                "id": {"type": "uuid", "primary_key": True},
                "status": {
                    "type": "enum",
                    "values": ["draft", "submitted"],
                    "required": True,
                },
                "total": {"type": "decimal", "required": True},
            },
            "constraints": {
                "check": [
                    {"field": "total", "op": "gte", "value": 0},
                    {
                        "any": [
                            {"field": "status", "op": "eq", "value": "draft"},
                            {"field": "status", "op": "eq", "value": "submitted"},
                        ]
                    },
                ]
            },
        }
    )

    model = map_model(definition)
    ddl = str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))

    assert 'CREATE TABLE sales_invoice_rtm' in ddl
    assert 'id UUID NOT NULL' in ddl
    assert 'status TEXT' in ddl
    assert 'total NUMERIC NOT NULL' in ddl
    assert 'total >= 0' in ddl
    assert "status = 'draft' OR status = 'submitted'" in ddl
