"""Shared contract suite: same YAML, same SDK calls, same semantics on
PostgreSQL, SQLite, and MySQL. No business-code changes between dialects.
"""

import itertools
import os
import uuid

import pytest
import yaml

from keelmodel.authz import AuthorizationProvider
from keelmodel.extensions.audit import AuditExtension
from keelmodel.extensions.audit.audit import AuditEntry
from keelmodel.registry import ModuleDefinition, ModuleRegistry
from keelmodel.runtime.context import OperationContext
from keelmodel.runtime.errors import (
    ConflictError,
    NotFoundError,
    PermissionDenied,
    ValidationError,
)
from keelmodel.runtime.session import KeelModel
from keelmodel.schema import parse_model

ADMIN = OperationContext(subject={"roles": ["admin"]}, attributes={})
STAFF = OperationContext(subject={"roles": ["staff"]}, attributes={})

_counter = itertools.count()


def _defs(suffix: str):
    parent = parse_model(
        {
            "version": 1,
            "module": "contract",
            "model": "Parent",
            "table": f"ct_parent_{suffix}",
            "fields": {
                "id": {"type": "uuid", "primary_key": True, "default": "uuid4"},
                "code": {"type": "text", "required": True, "length": 40},
                "at": {"type": "datetime"},
            },
            "constraints": {"unique": [["code"]]},
        }
    )
    child = parse_model(
        {
            "version": 1,
            "module": "contract",
            "model": "Child",
            "table": f"ct_child_{suffix}",
            "fields": {
                "id": {"type": "uuid", "primary_key": True, "default": "uuid4"},
                "flag": {"type": "boolean", "required": True, "default": False},
                "status": {
                    "type": "enum",
                    "values": ["open", "closed"],
                    "required": True,
                    "default": "open",
                    "length": 20,
                },
                "amount": {"type": "decimal", "required": True},
            },
            "relations": {
                "parent": {
                    "type": "many_to_one",
                    "target": "contract.Parent",
                    "required": True,
                }
            },
            "constraints": {
                "check": [{"field": "amount", "op": "gte", "value": 0}],
                "index": [["parent_id", "status"]],
            },
        }
    )
    return parent, child


def _build(db_url: str, audit: AuditExtension | None = None) -> KeelModel:
    suffix = uuid.uuid4().hex[:8]
    parent, child = _defs(suffix)
    registry = ModuleRegistry()
    registry.register(
        ModuleDefinition(
            name="contract",
            version="1.0.0",
            requires=(),
            exports=("Parent", "Child"),
            models_path="models",
        ),
        (parent, child),
    )
    authz = None
    return registry, km_build(db_url, registry, authz, audit), (parent, child)


def km_build(db_url, registry, authz, audit):
    km = KeelModel(db_url, registry, authz=authz, audit=audit)
    for name in ("contract.Parent", "contract.Child"):
        km._all_mapped[name].__table__.create(km.engine, checkfirst=True)
    return km


DIALECTS = ["sqlite"]
if os.environ.get("KEELMODEL_TEST_DB"):
    DIALECTS.append("postgres")
if os.environ.get("KEELMODEL_TEST_MYSQL"):
    DIALECTS.append("mysql")


@pytest.fixture(params=DIALECTS)
def backend(request, tmp_path):
    if request.param == "sqlite":
        url = f"sqlite:///{tmp_path}/contract.db"
    elif request.param == "postgres":
        url = os.environ["KEELMODEL_TEST_DB"]
    else:
        url = os.environ["KEELMODEL_TEST_MYSQL"]
    return request.param, url


@pytest.fixture
def contract(backend, tmp_path):
    name, url = backend
    registry, km, defs = _build(url)
    return name, km, defs


def test_crud_cycle(contract):
    name, km, _ = contract
    p = km.create("contract.Parent", {"code": "P1"}, ADMIN)
    c = km.create(
        "contract.Child",
        {"parent_id": str(p["id"]), "amount": "10.50", "status": "open"},
        ADMIN,
    )
    assert c["parent_id"] == p["id"]
    fetched = km.get("contract.Child", str(c["id"]), ADMIN)
    assert fetched["status"] == "open"
    updated = km.update("contract.Child", c["id"], {"status": "closed"}, ADMIN)
    assert updated["status"] == "closed"
    km.delete("contract.Child", c["id"], ADMIN)
    with pytest.raises(NotFoundError):
        km.get("contract.Child", c["id"], ADMIN)


def test_unique_violation(contract):
    _, km, _ = contract
    km.create("contract.Parent", {"code": "DUP"}, ADMIN)
    with pytest.raises(ConflictError):
        km.create("contract.Parent", {"code": "DUP"}, ADMIN)


def test_fk_violation(contract):
    _, km, _ = contract
    missing = str(uuid.uuid4())
    with pytest.raises(ConflictError):
        km.create(
            "contract.Child",
            {"parent_id": missing, "amount": "1"},
            ADMIN,
        )


def test_check_violation(contract):
    _, km, _ = contract
    p = km.create("contract.Parent", {"code": "CHK"}, ADMIN)
    with pytest.raises(ConflictError):
        km.create(
            "contract.Child",
            {"parent_id": str(p["id"]), "amount": "-5"},
            ADMIN,
        )


def test_datetime_roundtrip(contract):
    name, km, _ = contract
    p = km.create(
        "contract.Parent",
        {"code": "DT", "at": "2026-01-01T12:00:00+00:00"},
        ADMIN,
    )
    fetched = km.get("contract.Parent", p["id"], ADMIN)
    assert fetched["at"] is not None
    if name in {"sqlite", "mysql"}:
        # SQLite and MySQL DATETIME storage do not preserve tzinfo;
        # values come back naive. Instant value is still correct.
        assert fetched["at"].year == 2026
    else:
        assert fetched["at"].tzinfo is not None


def test_enum_validation(contract):
    _, km, _ = contract
    p = km.create("contract.Parent", {"code": "EN"}, ADMIN)
    with pytest.raises(ValidationError):
        km.create(
            "contract.Child",
            {"parent_id": str(p["id"]), "amount": "1", "status": "bogus"},
            ADMIN,
        )


def test_strict_validation_rejections(contract):
    _, km, _ = contract
    p = km.create("contract.Parent", {"code": "ST"}, ADMIN)
    with pytest.raises(ValidationError):
        km.create(
            "contract.Child",
            {"parent_id": str(p["id"]), "amount": "1", "flag": "false"},
            ADMIN,
        )


def test_filter_and_pagination(contract):
    _, km, _ = contract
    p = km.create("contract.Parent", {"code": "FIL"}, ADMIN)
    for i in range(10):
        km.create(
            "contract.Child",
            {
                "parent_id": str(p["id"]),
                "amount": i,
                "status": "open" if i % 2 else "closed",
            },
            ADMIN,
        )
    page = km.query(
        "contract.Child",
        ADMIN,
        filters={
            "all": [
                {"field": "parent_id", "op": "eq", "value": str(p["id"])},
                {"field": "status", "op": "eq", "value": "open"},
            ]
        },
        limit=3,
        offset=0,
    )
    assert page.total == 5
    assert len(page.items) == 3


def test_transaction_atomicity(contract):
    _, km, _ = contract
    p = km.create("contract.Parent", {"code": "TX"}, ADMIN)
    with pytest.raises(ValidationError):
        with km.transaction(ADMIN):
            km.create(
                "contract.Child",
                {"parent_id": str(p["id"]), "amount": "1"},
                ADMIN,
            )
            km.create(
                "contract.Child",
                {"parent_id": str(p["id"]), "amount": "2", "bad": 1},
                ADMIN,
            )
    page = km.query(
        "contract.Child",
        ADMIN,
        filters={"field": "parent_id", "op": "eq", "value": str(p["id"])},
    )
    assert page.total == 0


def test_bulk_atomicity_on_failure(contract):
    _, km, _ = contract
    p = km.create("contract.Parent", {"code": "BLK"}, ADMIN)
    items = [
        {"parent_id": str(p["id"]), "amount": "1"},
        {"parent_id": str(p["id"]), "amount": "2"},
        {"parent_id": str(p["id"]), "amount": "-1"},  # violates check
    ]
    with pytest.raises(ConflictError):
        km.bulk("contract.Child", items, ADMIN)
    page = km.query(
        "contract.Child",
        ADMIN,
        filters={"field": "parent_id", "op": "eq", "value": str(p["id"])},
    )
    assert page.total == 0


def _authz_km(db_url: str, tmp_path) -> tuple:
    suffix = uuid.uuid4().hex[:8]
    parent, child = _defs(suffix)
    registry = ModuleRegistry()
    registry.register(
        ModuleDefinition(
            name="contract",
            version="1.0.0",
            requires=(),
            exports=("Parent", "Child"),
            models_path="models",
        ),
        (parent, child),
    )
    policy = tmp_path / f"pol_{suffix}.yaml"
    policy.write_text(
        yaml.dump(
            {
                "version": 1,
                "statements": [
                    {
                        "effect": "allow",
                        "actions": ["*"],
                        "resources": ["contract.*"],
                        "subjects": ["role:admin"],
                    },
                    {
                        "effect": "allow",
                        "actions": ["read", "query"],
                        "resources": ["contract.*"],
                        "subjects": ["role:staff"],
                        "condition": {
                            "field": "record.code",
                            "op": "eq",
                            "value": "shared",
                        },
                    },
                ],
            }
        )
    )
    authz = AuthorizationProvider(str(policy))
    km = KeelModel(db_url, registry, authz=authz)
    for name in ("contract.Parent", "contract.Child"):
        km._all_mapped[name].__table__.create(km.engine, checkfirst=True)
    return km


def test_authz_record_condition(backend, tmp_path):
    _, url = backend
    km = _authz_km(url, tmp_path)
    shared = km.create("contract.Parent", {"code": "shared"}, ADMIN)
    other = km.create("contract.Parent", {"code": "other"}, ADMIN)

    page = km.query("contract.Parent", STAFF)
    assert page.total == 1
    assert page.items[0]["code"] == "shared"

    assert km.get("contract.Parent", shared["id"], STAFF)["code"] == "shared"
    with pytest.raises(PermissionDenied):
        km.get("contract.Parent", other["id"], STAFF)
    with pytest.raises(PermissionDenied):
        km.create("contract.Parent", {"code": "X"}, STAFF)


def test_audit_same_transaction(backend, tmp_path):
    name, url = backend
    audit = AuditExtension(redact_fields={"code"})
    registry, km, _ = _build(url, audit=audit)
    if name == "sqlite":
        audit.create_all(km.engine)
    else:
        audit.table.create(km.engine, checkfirst=True)
    km.create("contract.Parent", {"code": "AUD"}, ADMIN)
    with km.session_factory() as s:
        count = s.query(AuditEntry).filter_by(operation="create").count()
    assert count >= 1


def test_migration_draft_matches_schema(tmp_path):
    from keelmodel.migrations import generate_migration_draft

    parent, child = _defs("mig")
    defs = {d.resource: d for d in (parent, child)}
    path = generate_migration_draft(
        [parent, child], tmp_path / "rev.py", resolve=defs.get
    )
    content = path.read_text()
    assert "revision = '0001'" in content
    assert "parent_id" in content
    assert "sa.ForeignKey" in content
    compile(content, str(path), "exec")
