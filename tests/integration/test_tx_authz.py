"""Transaction atomicity + record-level authorization on SQLite."""

import itertools

import pytest
import yaml

from keelmodel.authz import AuthorizationProvider
from keelmodel.registry import ModuleDefinition, ModuleRegistry
from keelmodel.runtime.context import OperationContext
from keelmodel.runtime.errors import PermissionDenied, ValidationError
from keelmodel.runtime.session import KeelModel
from keelmodel.schema import parse_model

CTX_ADMIN = OperationContext(subject={"roles": ["admin"]}, attributes={})
CTX_STAFF = OperationContext(subject={"roles": ["staff"]}, attributes={})
_counter = itertools.count()


@pytest.fixture
def km_sqlite(tmp_path):
    defn = parse_model(
        {
            "version": 1,
            "module": "docs",
            "model": "Doc",
            "table": f"docs_doc_tx_{next(_counter)}",
            "fields": {
                "id": {"type": "uuid", "primary_key": True, "default": "uuid4"},
                "title": {"type": "text", "required": True},
                "owner": {"type": "text", "required": True},
            },
        }
    )
    registry = ModuleRegistry()
    registry.register(
        ModuleDefinition(
            name="docs",
            version="1.0.0",
            requires=(),
            exports=("Doc",),
            models_path="models",
        ),
        (defn,),
    )
    km = KeelModel(f"sqlite:///{tmp_path}/t.db", registry)
    km._models["docs.Doc"].__table__.create(km.engine)
    return km


@pytest.fixture
def km_authz(tmp_path):
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        yaml.dump(
            {
                "version": 1,
                "statements": [
                    {
                        "effect": "allow",
                        "actions": ["*"],
                        "resources": ["docs.*"],
                        "subjects": ["role:admin"],
                    },
                    {
                        "effect": "allow",
                        "actions": ["read", "query"],
                        "resources": ["docs.*"],
                        "subjects": ["role:staff"],
                        "condition": {
                            "field": "record.owner",
                            "op": "eq",
                            "value": "team-a",
                        },
                    },
                ],
            }
        )
    )
    defn = parse_model(
        {
            "version": 1,
            "module": "docs",
            "model": "Doc",
            "table": f"docs_doc_authz_{next(_counter)}",
            "fields": {
                "id": {"type": "uuid", "primary_key": True, "default": "uuid4"},
                "title": {"type": "text", "required": True},
                "owner": {"type": "text", "required": True},
            },
        }
    )
    registry = ModuleRegistry()
    registry.register(
        ModuleDefinition(
            name="docs",
            version="1.0.0",
            requires=(),
            exports=("Doc",),
            models_path="models",
        ),
        (defn,),
    )
    authz = AuthorizationProvider(str(policy))
    km = KeelModel(f"sqlite:///{tmp_path}/a.db", registry, authz=authz)
    km._models["docs.Doc"].__table__.create(km.engine)
    return km


def test_transaction_rolls_back_on_error(km_sqlite):
    with pytest.raises(ValidationError):
        with km_sqlite.transaction(CTX_ADMIN):
            km_sqlite.create(
                "docs.Doc", {"title": "A", "owner": "x"}, CTX_ADMIN
            )
            km_sqlite.create(
                "docs.Doc", {"title": "B", "bogus": 1}, CTX_ADMIN
            )
    page = km_sqlite.query("docs.Doc", CTX_ADMIN)
    assert page.total == 0


def test_transaction_commits_together(km_sqlite):
    with km_sqlite.transaction(CTX_ADMIN):
        km_sqlite.create("docs.Doc", {"title": "A", "owner": "x"}, CTX_ADMIN)
        km_sqlite.create("docs.Doc", {"title": "B", "owner": "x"}, CTX_ADMIN)
    assert km_sqlite.query("docs.Doc", CTX_ADMIN).total == 2


def test_record_condition_filters_query(km_authz):
    a = km_authz.create("docs.Doc", {"title": "ta", "owner": "team-a"}, CTX_ADMIN)
    km_authz.create("docs.Doc", {"title": "tb", "owner": "team-b"}, CTX_ADMIN)

    staff_page = km_authz.query("docs.Doc", CTX_STAFF)
    assert staff_page.total == 1
    assert staff_page.items[0]["id"] == a["id"]

    admin_page = km_authz.query("docs.Doc", CTX_ADMIN)
    assert admin_page.total == 2


def test_record_condition_denies_get(km_authz):
    a = km_authz.create("docs.Doc", {"title": "ta", "owner": "team-a"}, CTX_ADMIN)
    b = km_authz.create("docs.Doc", {"title": "tb", "owner": "team-b"}, CTX_ADMIN)

    assert km_authz.get("docs.Doc", a["id"], CTX_STAFF)["title"] == "ta"
    with pytest.raises(PermissionDenied):
        km_authz.get("docs.Doc", b["id"], CTX_STAFF)


def test_staff_cannot_write(km_authz):
    with pytest.raises(PermissionDenied):
        km_authz.create("docs.Doc", {"title": "x", "owner": "team-a"}, CTX_STAFF)
