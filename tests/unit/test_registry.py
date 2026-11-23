from pathlib import Path

import pytest

from keelmodel.registry import ModuleRegistry, RegistryError, load_module, parse_module
from keelmodel.schema import parse_model


def test_registers_public_models_and_hides_private_models():
    manifest = parse_module(
        {
            "version": 1,
            "name": "sales",
            "module_version": "1.0.0",
            "requires": [],
            "exports": {"models": ["Invoice"]},
        }
    )
    public = parse_model(
        {
            "version": 1,
            "module": "sales",
            "model": "Invoice",
            "fields": {"id": {"type": "uuid", "primary_key": True}},
        }
    )
    private = parse_model(
        {
            "version": 1,
            "module": "sales",
            "model": "InternalNote",
            "fields": {"id": {"type": "uuid", "primary_key": True}},
        }
    )

    registry = ModuleRegistry()
    registry.register(manifest, [public, private])

    assert registry.get_model("sales.Invoice") is public
    with pytest.raises(RegistryError, match="not registered or public"):
        registry.get_model("sales.InternalNote")


def test_dependency_must_be_registered():
    module = parse_module(
        {
            "version": 1,
            "name": "sales",
            "module_version": "1.0.0",
            "requires": [{"name": "core", "version": ">=1.0,<2.0"}],
            "exports": {"models": ["Invoice"]},
        }
    )
    model = parse_model(
        {
            "version": 1,
            "module": "sales",
            "model": "Invoice",
            "fields": {"id": {"type": "uuid", "primary_key": True}},
        }
    )
    with pytest.raises(RegistryError, match="unregistered module"):
        ModuleRegistry().register(module, [model])


def test_loads_module_manifest_with_relative_source(tmp_path: Path):
    path = tmp_path / "module.yaml"
    path.write_text(
        "version: 1\nname: sales\nmodule_version: '1.2.0'\nrequires: []\n"
        "exports:\n  models: [Invoice]\n",
        encoding="utf-8",
    )
    module = load_module(path)
    assert str(module.version) == "1.2.0"
    assert module.models_path == "models"
