from pathlib import Path

from keelmodel.registry import ModuleRegistry, load_module
from keelmodel.runtime.session import KeelModel
from keelmodel.schema import load_model

EXAMPLE = Path("examples/sales")


def test_sales_module_loads_registers_and_maps():
    module = load_module(EXAMPLE / "keelmodule.yaml")
    models = [
        load_model(p)
        for p in sorted((EXAMPLE / "models").glob("*.yaml"))
    ]
    registry = ModuleRegistry()
    registry.register(module, models)

    assert {m.resource for m in registry.models} == {
        "sales.Customer",
        "sales.Invoice",
        "sales.InvoiceLine",
    }

    km = KeelModel("postgresql://localhost/unused", registry)
    assert set(km._models) == {"sales.Customer", "sales.Invoice", "sales.InvoiceLine"}

    invoice = km._models["sales.Invoice"]
    assert "customer_id" in invoice.__table__.columns
    assert hasattr(invoice, "customer")
    assert hasattr(invoice, "lines")
