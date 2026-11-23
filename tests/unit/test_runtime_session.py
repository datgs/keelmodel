import itertools
from unittest.mock import MagicMock, patch

import pytest

from keelmodel.registry import ModuleDefinition, ModuleRegistry
from keelmodel.runtime.context import OperationContext
from keelmodel.runtime.errors import ValidationError
from keelmodel.runtime.session import KeelModel
from keelmodel.schema import parse_model

_module_counter = itertools.count()


def _registry_with_model(module_name: str = "sales") -> ModuleRegistry:
    table_id = next(_module_counter)
    model = parse_model(
        {
            "version": 1,
            "module": module_name,
            "model": "Invoice",
            "table": f"{module_name}_invoice_{table_id}",
            "fields": {
                "id": {"type": "uuid", "primary_key": True},
                "name": {"type": "text", "required": True},
            },
        }
    )
    registry = ModuleRegistry()
    module = ModuleDefinition(
        name=module_name,
        version="1.0.0",
        requires=(),
        exports=("Invoice",),
        models_path="models",
    )
    registry.register(module, (model,))
    return registry


def test_keelmodel_create_validates_unknown_fields():
    registry = _registry_with_model("sales")
    km = KeelModel("postgresql://localhost/test", registry)
    context = OperationContext(subject={}, attributes={})

    with pytest.raises(ValidationError, match="unknown field"):
        km.create("sales.Invoice", {"id": "x", "name": "n", "bogus": 1}, context)


def test_keelmodel_get_returns_model_fields():
    registry = _registry_with_model("billing")
    km = KeelModel("postgresql://localhost/test", registry)
    context = OperationContext(subject={}, attributes={})

    instance = MagicMock()
    instance.__table__ = MagicMock()
    id_col = MagicMock()
    id_col.name = "id"
    name_col = MagicMock()
    name_col.name = "name"
    instance.__table__.columns = [id_col, name_col]
    instance.id = "123e4567-e89b-12d3-a456-426614174000"
    instance.name = "Invoice"

    with patch.object(km, "_session") as mock_session:
        mock_session.return_value.__enter__.return_value.get.return_value = instance
        result = km.get(
            "billing.Invoice", "123e4567-e89b-12d3-a456-426614174000", context
        )
    assert result["id"] == "123e4567-e89b-12d3-a456-426614174000"
    assert result["name"] == "Invoice"


def test_keelmodel_bulk_constructs_and_commits_atomically():
    registry = _registry_with_model("inventory")
    km = KeelModel("postgresql://localhost/test", registry)
    context = OperationContext(subject={}, attributes={})

    with patch.object(km, "_session") as mock_session:
        session = mock_session.return_value.__enter__.return_value
        items = [
            {"id": "123e4567-e89b-12d3-a456-426614174000", "name": "one"},
            {"id": "123e4567-e89b-12d3-a456-426614174001", "name": "two"},
        ]
        result = km.bulk("inventory.Invoice", items, context)
        assert len(result) == 2
        session.add_all.assert_called_once()
        session.commit.assert_called_once()
