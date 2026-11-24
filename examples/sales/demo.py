"""Self-contained Sales walkthrough covering the full v1 surface.

Targets:
    SQLite (default, temporary file — nothing to clean up):
        uv run python examples/sales/demo.py

    PostgreSQL (explicit, dedicated test database — additive only;
    every record is namespaced by a run id, no drop_all):
        KEELMODEL_DEMO_PG=postgresql://user:pass@host/db \
            uv run python examples/sales/demo.py --postgres

    Postgres schema drift: additive create_all cannot alter an existing
    table. To rebuild stale demo tables on a dedicated test database,
    opt in explicitly with KEELMODEL_RESET=1 (drops sales_* + audit
    tables — destructive, never the default).

Safe to re-run: each run uses a unique run id for unique-constrained
values, and migration drafts are written to a temp directory.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

from keelmodel.authz import AuthorizationProvider
from keelmodel.extensions.audit import AuditExtension
from keelmodel.extensions.audit.audit import AuditEntry
from keelmodel.registry import ModuleRegistry, load_module
from keelmodel.runtime.base import Base
from keelmodel.runtime.context import OperationContext
from keelmodel.runtime.session import KeelModel
from keelmodel.schema import load_model

ROOT = Path(__file__).parent
RUN = uuid.uuid4().hex[:8]  # namespaces unique values per run


def resolve_db_url(argv: list[str]) -> str:
    if "--postgres" in argv:
        url = os.environ.get("KEELMODEL_DEMO_PG")
        if not url:
            print(
                "set KEELMODEL_DEMO_PG to a dedicated test database URL",
                file=sys.stderr,
            )
            raise SystemExit(2)
        return url
    # default: disposable SQLite file — the safest possible target
    tmp = tempfile.NamedTemporaryFile(
        prefix="keelmodel_demo_", suffix=".db", delete=False
    )
    tmp.close()
    os.unlink(tmp.name)  # let SQLite create it fresh
    return f"sqlite:///{tmp.name}"


def build(db_url: str) -> tuple[KeelModel, ModuleRegistry]:
    module = load_module(ROOT / "keelmodule.yaml")
    models = [load_model(p) for p in sorted((ROOT / "models").glob("*.yaml"))]
    registry = ModuleRegistry()
    registry.register(module, models)

    authz = AuthorizationProvider(
        ROOT / "policies" / "authorization.yaml", enable_field_rules=True
    )
    audit = AuditExtension(redact_fields={"email"})
    km = KeelModel(db_url, registry, authz=authz, audit=audit)
    if os.environ.get("KEELMODEL_RESET") == "1":
        # explicit opt-in only: rebuild demo tables on a dedicated
        # database after schema drift. Never run this on a shared DB.
        Base.metadata.drop_all(km.engine, checkfirst=True)
        audit.table.drop(km.engine, checkfirst=True)
    Base.metadata.create_all(km.engine)
    audit.create_all(km.engine)
    return km, registry


def expect(ok: bool, label: str) -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")


def main(argv: list[str]) -> int:
    db_url = resolve_db_url(argv)
    km, registry = build(db_url)
    print(f"dialect: {km.engine.dialect.name}  run: {RUN}")

    admin = OperationContext(subject={"roles": ["admin"]}, attributes={})
    viewer = OperationContext(subject={"roles": ["viewer"]}, attributes={})

    print("\n== CRUD + relations ==")
    customer = km.create(
        "sales.Customer",
        {"name": f"ACME-{RUN}", "email": f"https://acme-{RUN}.example"},
        admin,
    )
    print("created customer", customer["id"])

    invoice = km.create(
        "sales.Invoice",
        {
            "number": f"INV-{RUN}",
            "total": "100.00",
            "customer_id": str(customer["id"]),
        },
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
        filters={"field": "number", "op": "eq", "value": f"INV-{RUN}"},
        order=["-number"],
    )
    expect(page.total == 1, "filtered query finds the invoice")

    print("\n== record-level authz ==")
    try:
        km.get("sales.Invoice", invoice["id"], viewer)
        expect(False, "viewer cannot read draft invoice")
    except Exception as exc:
        expect(
            type(exc).__name__ == "PermissionDenied",
            f"viewer denied draft invoice ({type(exc).__name__})",
        )

    paid = km.update("sales.Invoice", invoice["id"], {"status": "paid"}, admin)
    visible = km.query("sales.Invoice", viewer)
    expect(
        all(i["status"] in {"submitted", "paid"} for i in visible.items),
        "viewer query only sees submitted/paid invoices (SQL filter)",
    )
    fetched = km.get("sales.Invoice", paid["id"], viewer)
    expect(fetched["status"] == "paid", "viewer reads a paid invoice")

    print("\n== field-level authz ==")
    customer = km.update(
        "sales.Customer", customer["id"], {"tax_id": f"TAX-{RUN}"}, admin
    )
    seen = km.get("sales.Customer", customer["id"], viewer)
    expect("tax_id" not in seen, "tax_id omitted from viewer output")
    try:
        km.query(
            "sales.Customer",
            viewer,
            filters={"field": "tax_id", "op": "eq", "value": "x"},
        )
        expect(False, "viewer cannot filter on tax_id")
    except Exception as exc:
        expect(
            type(exc).__name__ == "PermissionDenied",
            f"viewer cannot filter on tax_id ({type(exc).__name__})",
        )
    try:
        km.create(
            "sales.Invoice",
            {"number": f"X-{RUN}", "customer_id": str(customer["id"])},
            viewer,
        )
        expect(False, "viewer cannot create invoices")
    except Exception as exc:
        expect(
            type(exc).__name__ == "PermissionDenied",
            f"viewer cannot create invoices ({type(exc).__name__})",
        )

    print("\n== transaction ==")
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
                {
                    "description": "T2",
                    "quantity": "bad",
                    "invoice_id": str(invoice["id"]),
                },
                admin,
            )
        expect(False, "invalid row aborts the transaction")
    except Exception as exc:
        expect(
            type(exc).__name__ == "ValidationError",
            f"invalid row aborts the transaction ({type(exc).__name__})",
        )
    inside = km.query(
        "sales.InvoiceLine",
        admin,
        filters={
            "all": [
                {"field": "invoice_id", "op": "eq", "value": str(invoice["id"])},
                {"field": "description", "op": "eq", "value": "T1"},
            ]
        },
    )
    expect(inside.total == 0, "rolled-back row is not persisted")

    print("\n== generated artifacts ==")
    spec = importlib.util.spec_from_file_location(
        "gen_invoice", ROOT / "generated" / "invoice.py"
    )
    gen_invoice = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen_invoice)
    gen_model = gen_invoice.build_model(
        registry.get_model_any, km.engine.dialect.name
    )
    # use the generated mapped class for a real operation
    with km.session_factory() as session:
        count = session.query(gen_model).count()
    expect(count >= 1, f"generated class queries ({count} invoice rows)")

    print("\n== migration draft ==")
    from keelmodel.migrations import generate_migration_draft

    with tempfile.TemporaryDirectory() as tmpdir:
        draft = generate_migration_draft(
            [load_model(p) for p in sorted((ROOT / "models").glob("*.yaml"))],
            Path(tmpdir) / "0001_sales.py",
            resolve=registry.get_model_any,
        )
        # prove it executes: run upgrade/downgrade on an isolated
        # in-memory SQLite connection via Alembic
        import sqlalchemy as sa
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        spec = importlib.util.spec_from_file_location("rev", draft)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        eng = sa.create_engine("sqlite:///:memory:")
        conn = eng.connect()
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            mod.upgrade()
            tables = sa.inspect(conn).get_table_names()
            mod.downgrade()
        conn.close()
        eng.dispose()
    expect(
        "sales_invoice" in tables,
        f"migration draft executed upgrade ({len(tables)} tables)",
    )

    print("\n== audit ==")
    with km.session_factory() as session:
        audit_row = (
            session.query(AuditEntry)
            .filter_by(resource="sales.Customer", operation="create")
            .order_by(AuditEntry.id.asc())
            .first()
        )
    expect(audit_row is not None, "audit entry recorded")
    if audit_row:
        changes = audit_row.changes or {}
        email_val = (changes.get("email") or {}).get("new")
        expect(
            email_val == "[redacted]",
            f"email redacted in audit ({email_val!r})",
        )

    print("\n== delete + bulk + perf ==")
    km.delete("sales.InvoiceLine", line["id"], admin)
    print("deleted line", line["id"])

    started = time.perf_counter()
    items = [
        {"name": f"C{i}-{RUN}", "email": f"https://c{i}-{RUN}.example"}
        for i in range(500)
    ]
    km.bulk("sales.Customer", items, admin)
    print(f"bulk 500 customers: {time.perf_counter() - started:.2f}s")

    started = time.perf_counter()
    total = 0
    for i in range(200):
        page = km.query(
            "sales.Customer",
            admin,
            filters={"field": "name", "op": "eq", "value": f"C{i}-{RUN}"},
        )
        total += page.total
    elapsed = time.perf_counter() - started
    print(
        f"200 filtered queries: {elapsed:.2f}s "
        f"({total} hits, {200 / elapsed:.0f} qps)"
    )
    expect(total == 200, "all bulk rows queryable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
