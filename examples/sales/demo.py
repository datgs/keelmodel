"""End-to-end demo: load sales module, register, map, run CRUD on Postgres.

Usage:
    KEELMODEL_DB="postgresql://postgres:postgres@localhost:5544/postgres" \
        uv run python examples/sales/demo.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from keelmodel.authz import AuthorizationProvider
from keelmodel.extensions.audit import AuditExtension
from keelmodel.registry import ModuleRegistry, load_module
from keelmodel.runtime.base import Base
from keelmodel.runtime.context import OperationContext
from keelmodel.runtime.session import KeelModel
from keelmodel.schema import load_model

ROOT = Path(__file__).parent
DB_URL = os.environ.get("KEELMODEL_DB")


def build() -> KeelModel:
    module = load_module(ROOT / "keelmodule.yaml")
    models = [load_model(p) for p in sorted((ROOT / "models").glob("*.yaml"))]
    registry = ModuleRegistry()
    registry.register(module, models)

    authz = AuthorizationProvider(
        ROOT / "policies" / "authorization.yaml", enable_field_rules=True
    )
    audit = AuditExtension(redact_fields={"email"})
    km = KeelModel(DB_URL, registry, authz=authz, audit=audit)
    if os.environ.get("KEELMODEL_RESET") == "1":
        Base.metadata.drop_all(km.engine, checkfirst=True)
        audit.table.drop(km.engine, checkfirst=True)
    Base.metadata.create_all(km.engine)
    audit.create_all(km.engine)
    return km


def main() -> int:
    if not DB_URL:
        print("set KEELMODEL_DB", file=sys.stderr)
        return 2

    km = build()
    admin = OperationContext(subject={"roles": ["admin"]}, attributes={})
    viewer = OperationContext(subject={"roles": ["viewer"]}, attributes={})

    customer = km.create(
        "sales.Customer", {"name": "ACME", "email": "https://acme.example"}, admin
    )
    print("created customer", customer["id"])

    invoice = km.create(
        "sales.Invoice",
        {"number": "INV-1", "total": "100.00", "customer_id": str(customer["id"])},
        admin,
    )
    print("created invoice", invoice["number"], "total", invoice["total"])

    line = km.create(
        "sales.InvoiceLine",
        {
            "description": "Widget",
            "quantity": 2,
            "unit_price": "50.00",
            "invoice_id": str(invoice["id"]),
        },
        admin,
    )
    print("created line", line["description"])

    page = km.query(
        "sales.Invoice",
        admin,
        filters={"field": "total", "op": "gte", "value": 0},
        order=["-number"],
    )
    print("query:", page.total, "invoice(s)")

    try:
        km.get("sales.Invoice", invoice["id"], viewer)
        print("viewer read draft invoice: allowed")
    except Exception as exc:
        print("viewer read draft invoice:", type(exc).__name__, exc)

    paid = km.update("sales.Invoice", invoice["id"], {"status": "paid"}, admin)
    visible = km.query("sales.Invoice", viewer)
    print(
        "viewer query (record-level filter):",
        visible.total,
        "invoice(s) — only submitted/paid are visible",
    )
    fetched = km.get("sales.Invoice", paid["id"], viewer)
    print("viewer read paid invoice: allowed, status =", fetched["status"])

    customer = km.update(
        "sales.Customer", customer["id"], {"tax_id": "TAX-42"}, admin
    )
    seen = km.get("sales.Customer", customer["id"], viewer)
    print(
        "viewer customer fields (field-level authz):",
        sorted(seen.keys()),
        "— tax_id omitted",
    )

    try:
        km.create("sales.Invoice", {"number": "X", "customer_id": str(customer["id"])}, viewer)
        print("viewer create: allowed")
    except Exception as exc:
        print("viewer create:", type(exc).__name__, exc)

    # transaction(): all-or-nothing — a validation error mid-block rolls
    # back everything done inside the same transaction.
    try:
        with km.transaction(admin):
            km.create(
                "sales.InvoiceLine",
                {
                    "description": "T1",
                    "quantity": 1,
                    "unit_price": "1",
                    "invoice_id": str(invoice["id"]),
                },
                admin,
            )
            km.create(
                "sales.InvoiceLine",
                {"description": "T2", "quantity": "bad", "invoice_id": str(invoice["id"])},
                admin,
            )
    except Exception as exc:
        print("transaction rolled back:", type(exc).__name__)
    inside = km.query(
        "sales.InvoiceLine",
        admin,
        filters={"field": "invoice_id", "op": "eq", "value": str(invoice["id"])},
    )
    print("lines after failed tx:", inside.total, "(only the earlier demo line)")

    # Generated artifacts: embed the YAML and expose definition() +
    # build_model() — the same mapped class the SDK uses.
    sys.path.insert(0, str(ROOT / "generated"))
    import invoice as gen_invoice

    gen_def = gen_invoice.definition()
    registry = ModuleRegistry()
    registry.register(
        load_module(ROOT / "keelmodule.yaml"),
        [load_model(p) for p in sorted((ROOT / "models").glob("*.yaml"))],
    )
    gen_model = gen_invoice.build_model(
        registry.get_model_any, km.engine.dialect.name
    )
    print(
        "generated artifact:",
        gen_def.resource,
        "→ mapped table",
        gen_model.__table__.name,
    )

    # Migration drafts are reviewable output, never applied automatically.
    from keelmodel.migrations import generate_migration_draft

    draft = generate_migration_draft(
        [load_model(p) for p in sorted((ROOT / "models").glob("*.yaml"))],
        ROOT / "migrations" / "0001_sales.py",
        resolve=lambda r: {m.resource: m for m in km._definitions.values()}.get(r),
    )
    print("migration draft:", draft)

    started = time.perf_counter()
    items = [{"name": f"C{i}", "email": f"https://c{i}.example"} for i in range(500)]
    km.bulk("sales.Customer", items, admin)
    print(f"bulk 500 customers: {time.perf_counter() - started:.2f}s")

    started = time.perf_counter()
    total = 0
    for i in range(200):
        page = km.query(
            "sales.Customer",
            admin,
            filters={"field": "name", "op": "eq", "value": f"C{i}"},
        )
        total += page.total
    elapsed = time.perf_counter() - started
    print(f"200 filtered queries: {elapsed:.2f}s ({total} hits, {200/elapsed:.0f} qps)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
