import pytest

from keelmodel.registry import ModuleDefinition, ModuleRegistry
from keelmodel.runtime.models import map_model, wire_relationships
from keelmodel.schema import SchemaError, parse_model


def _make(*model_dicts):
    models = tuple(parse_model(d) for d in model_dicts)
    registry = ModuleRegistry()
    by_module = {}
    for m in models:
        by_module.setdefault(m.module, []).append(m)
    for module_name, module_models in by_module.items():
        registry.register(
            ModuleDefinition(
                name=module_name,
                version="1.0.0",
                requires=(),
                exports=tuple(m.name for m in module_models),
                models_path="models",
            ),
            module_models,
        )
    return registry, models


def test_many_to_one_creates_fk_column():
    customer = {
        "version": 1,
        "module": "sales",
        "model": "Customer",
        "table": "sales_customer_m2o",
        "fields": {"id": {"type": "uuid", "primary_key": True}},
    }
    invoice = {
        "version": 1,
        "module": "sales",
        "model": "Invoice",
        "table": "sales_invoice_m2o",
        "fields": {"id": {"type": "uuid", "primary_key": True}},
        "relations": {"customer": {"type": "many_to_one", "target": "sales.Customer"}},
    }
    registry, (cust_def, inv_def) = _make(customer, invoice)
    resolved = registry.get_model_any
    cust_type = map_model(cust_def, resolved)
    inv_type = map_model(inv_def, resolved)

    assert "customer_id" in inv_type.__table__.columns
    fk = next(iter(inv_type.__table__.columns["customer_id"].foreign_keys))
    assert fk.column.table.name == "sales_customer_m2o"

    mapped = {cust_def.resource: cust_type, inv_def.resource: inv_type}
    wire_relationships(inv_def, inv_type, mapped, resolved)
    assert hasattr(inv_type, "customer")


def test_one_to_many_wires_back_populates():
    line = {
        "version": 1,
        "module": "sales",
        "model": "Line",
        "table": "sales_line_o2m",
        "fields": {"id": {"type": "uuid", "primary_key": True}},
        "relations": {"invoice": {"type": "many_to_one", "target": "sales.Invoice"}},
    }
    invoice = {
        "version": 1,
        "module": "sales",
        "model": "Invoice",
        "table": "sales_invoice_o2m",
        "fields": {"id": {"type": "uuid", "primary_key": True}},
        "relations": {
            "lines": {
                "type": "one_to_many",
                "target": "sales.Line",
                "mapped_by": "invoice",
            }
        },
    }
    registry, (line_def, inv_def) = _make(line, invoice)
    resolved = registry.get_model_any
    line_type = map_model(line_def, resolved)
    inv_type = map_model(inv_def, resolved)
    mapped = {line_def.resource: line_type, inv_def.resource: inv_type}
    wire_relationships(line_def, line_type, mapped, resolved)
    wire_relationships(inv_def, inv_type, mapped, resolved)
    from sqlalchemy.orm import configure_mappers

    configure_mappers()
    assert hasattr(inv_type, "lines")
    assert hasattr(line_type, "invoice")


def test_reject_one_to_many_without_mapped_by():
    with pytest.raises(SchemaError, match="mapped_by"):
        parse_model(
            {
                "version": 1,
                "module": "sales",
                "model": "Invoice",
                "fields": {"id": {"type": "uuid", "primary_key": True}},
                "relations": {
                    "lines": {"type": "one_to_many", "target": "sales.Line"}
                },
            }
        )
