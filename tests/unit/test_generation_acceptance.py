"""Generated artifacts must be usable: definition() + build_model()."""

import importlib.util
import sys

from keelmodel.generation import generate_model
from keelmodel.registry import ModuleDefinition, ModuleRegistry
from keelmodel.runtime.context import OperationContext
from keelmodel.runtime.session import KeelModel

CTX = OperationContext(subject={"roles": ["admin"]}, attributes={})


_SOURCE = """
version: 1
module: docs
model: Doc
table: {table}
fields:
  id: {{type: uuid, primary_key: true, default: uuid4}}
  title: {{type: text, required: true}}
"""


def _load_generated(tmp_path, name, table):
    src = tmp_path / f"{name}.yaml"
    src.write_text(_SOURCE.format(table=table))
    out = generate_model(src, tmp_path / "gen" / name)
    spec = importlib.util.spec_from_file_location(f"gen_{name}", out)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"gen_{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_generated_definition_and_build_model(tmp_path):
    mod = _load_generated(tmp_path, "doca", "gendocs_a")
    definition = mod.definition()
    assert definition.resource == "docs.Doc"
    assert definition.table == "gendocs_a"

    model = mod.build_model(lambda resource: None, "sqlite")
    assert model.__tablename__ == "gendocs_a"
    assert "title" in {c.name for c in model.__table__.columns}


def test_generated_definition_end_to_end(tmp_path):
    mod = _load_generated(tmp_path, "docb", "gendocs_b")
    definition = mod.definition()

    registry = ModuleRegistry()
    registry.register(
        ModuleDefinition(
            name="docs",
            version="1.0.0",
            requires=(),
            exports=("Doc",),
            models_path="models",
        ),
        (definition,),
    )
    km = KeelModel(f"sqlite:///{tmp_path}/gen.db", registry)
    model = km._all_mapped["docs.Doc"]
    model.__table__.create(km.engine, checkfirst=True)
    created = km.create("docs.Doc", {"title": "gen"}, CTX)
    assert created["title"] == "gen"
    assert km.get("docs.Doc", created["id"], CTX)["id"] == created["id"]
