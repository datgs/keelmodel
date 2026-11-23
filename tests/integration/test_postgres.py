import os
import uuid

import pytest

from keelmodel.registry import ModuleDefinition, ModuleRegistry
from keelmodel.runtime.context import OperationContext
from keelmodel.runtime.session import KeelModel
from keelmodel.schema import parse_model

pytestmark = pytest.mark.skipif(
    not os.environ.get("KEELMODEL_TEST_DB"),
    reason="KEELMODEL_TEST_DB not set — requires running PostgreSQL",
)


@pytest.fixture
def keelmodel():
    db_url = os.environ["KEELMODEL_TEST_DB"]
    suffix = uuid.uuid4().hex[:8]
    model = parse_model(
        {
            "version": 1,
            "module": "test",
            "model": "Widget",
            "table": f"test_widget_{suffix}",
            "fields": {
                "id": {"type": "uuid", "primary_key": True, "default": "uuid4"},
                "name": {"type": "text", "required": True},
                "count": {"type": "integer", "default": 0},
            },
        }
    )
    registry = ModuleRegistry()
    registry.register(
        ModuleDefinition(
            name="test",
            version="1.0.0",
            requires=(),
            exports=("Widget",),
            models_path="models",
        ),
        (model,),
    )
    km = KeelModel(db_url, registry)
    model_type = km._models["test.Widget"]
    model_type.__table__.create(km.engine, checkfirst=True)
    yield km
    model_type.__table__.drop(km.engine, checkfirst=True)
    km.engine.dispose()


def test_create_get_update_delete_cycle(keelmodel):
    ctx = OperationContext(subject={}, attributes={})
    item = keelmodel.create(
        "test.Widget", {"name": "alpha", "count": 5}, ctx
    )
    assert item["name"] == "alpha"
    assert item["count"] == 5
    assert item["id"] is not None

    fetched = keelmodel.get("test.Widget", item["id"], ctx)
    assert fetched["name"] == "alpha"

    updated = keelmodel.update(
        "test.Widget", item["id"], {"name": "beta"}, ctx
    )
    assert updated["name"] == "beta"
    assert updated["count"] == 5

    keelmodel.delete("test.Widget", item["id"], ctx)
    with pytest.raises(Exception):
        keelmodel.get("test.Widget", item["id"], ctx)


def test_query_with_filter_and_pagination(keelmodel):
    ctx = OperationContext(subject={}, attributes={})
    for i in range(5):
        keelmodel.create(
            "test.Widget", {"name": f"w{i}", "count": i}, ctx
        )

    page = keelmodel.query(
        "test.Widget",
        ctx,
        filters={"field": "count", "op": "gte", "value": 2},
        limit=10,
        offset=0,
    )
    assert len(page.items) == 3
    assert page.total == 3

    page2 = keelmodel.query(
        "test.Widget",
        ctx,
        filters={"field": "name", "op": "eq", "value": "w0"},
    )
    assert len(page2.items) == 1
    assert page2.items[0]["name"] == "w0"


def test_bulk_atomic(keelmodel):
    ctx = OperationContext(subject={}, attributes={})
    items = [{"name": f"b{i}", "count": i} for i in range(3)]
    results = keelmodel.bulk("test.Widget", items, ctx)
    assert len(results) == 3
    assert all(r["name"].startswith("b") for r in results)
