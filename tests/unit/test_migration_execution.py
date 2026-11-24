"""Migration drafts must actually execute via Alembic, not just compile."""

import importlib.util

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from keelmodel.migrations import generate_migration_draft
from keelmodel.schema import parse_model


def _defs():
    customer = parse_model(
        {
            "version": 1,
            "module": "m",
            "model": "Customer",
            "table": "mig_customer",
            "fields": {
                "id": {"type": "uuid", "primary_key": True, "default": "uuid4"},
                "name": {"type": "text", "required": True},
                "total": {"type": "decimal", "default": 0},
                "active": {"type": "boolean", "default": True},
                "note": {"type": "text", "default": "it's"},
            },
        }
    )
    invoice = parse_model(
        {
            "version": 1,
            "module": "m",
            "model": "Invoice",
            "table": "mig_invoice",
            "fields": {
                "id": {"type": "uuid", "primary_key": True, "default": "uuid4"},
                "amount": {"type": "decimal", "required": True},
            },
            "relations": {
                "customer": {
                    "type": "many_to_one",
                    "target": "m.Customer",
                    "required": True,
                }
            },
            "constraints": {"unique": [["amount"]]},
        }
    )
    return customer, invoice


def test_draft_executes_upgrade_downgrade(tmp_path):
    customer, invoice = _defs()
    defs = {d.resource: d for d in (customer, invoice)}
    path = generate_migration_draft(
        [customer, invoice], tmp_path / "rev1.py", resolve=defs.get
    )

    spec = importlib.util.spec_from_file_location("rev1", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    engine = sa.create_engine("sqlite:///:memory:")
    conn = engine.connect()
    ctx = MigrationContext.configure(conn)
    try:
        # `alembic.op` resolves against the active Operations context;
        # this proves the draft executes without touching a database
        # schema outside this isolated in-memory connection.
        with Operations.context(ctx):
            mod.upgrade()
            inspector = sa.inspect(conn)
            tables = set(inspector.get_table_names())
            assert {"mig_customer", "mig_invoice"} <= tables

            cols = {c["name"] for c in inspector.get_columns("mig_invoice")}
            assert "customer_id" in cols

            # server_default values must be valid SQL literals
            conn.execute(
                sa.text('INSERT INTO mig_customer (id, name) VALUES (:id, :name)'),
                {"id": "00000000-0000-0000-0000-000000000001", "name": "x"},
            )
            row = conn.execute(
                sa.text("SELECT total, active, note FROM mig_customer")
            ).fetchone()
            assert row is not None

            mod.downgrade()
            inspector = sa.inspect(conn)
            assert inspector.get_table_names() == []
    finally:
        conn.close()
        engine.dispose()


def test_no_overwrite_without_force(tmp_path):
    customer, invoice = _defs()
    defs = {d.resource: d for d in (customer, invoice)}
    target = tmp_path / "rev.py"
    target.write_text("existing")
    try:
        generate_migration_draft(
            [customer], target, resolve=defs.get, overwrite=False
        )
    except FileExistsError:
        pass
    else:
        raise AssertionError("expected FileExistsError")
    assert target.read_text() == "existing"
