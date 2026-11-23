from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import yaml
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from keelmodel.schema import (
    ModelDefinition,
    ModuleDefinition,
    ModuleDependency,
    SchemaError,
    _identifier,
    _keys,
    _UniqueKeyLoader,
)


class RegistryError(ValueError):
    pass


class ModuleRegistry:
    def __init__(self) -> None:
        self._modules: dict[str, ModuleDefinition] = {}
        self._models: dict[str, ModelDefinition] = {}
        self._all_models: dict[str, ModelDefinition] = {}
        self._tables: dict[str, str] = {}

    @property
    def modules(self) -> tuple[ModuleDefinition, ...]:
        return tuple(self._modules.values())

    @property
    def models(self) -> tuple[ModelDefinition, ...]:
        return tuple(self._models.values())

    def register(
        self,
        module: ModuleDefinition,
        models: Iterable[ModelDefinition],
    ) -> None:
        if module.name in self._modules:
            raise RegistryError(f"module {module.name!r} is already registered")

        module_models = tuple(models)
        if any(model.module != module.name for model in module_models):
            raise RegistryError(f"all models must belong to module {module.name!r}")
        model_names = {model.name for model in module_models}
        missing_exports = set(module.exports) - model_names
        if missing_exports:
            raise RegistryError(
                f"module {module.name!r} exports unknown model(s): {sorted(missing_exports)!r}"
            )

        for dependency in module.requires:
            installed = self._modules.get(dependency.name)
            if installed is None:
                raise RegistryError(
                    f"module {module.name!r} requires unregistered module {dependency.name!r}"
                )
            if installed.version not in SpecifierSet(dependency.version):
                raise RegistryError(
                    f"module {module.name!r} requires {dependency.name} {dependency.version}; "
                    f"found {installed.version}"
                )

        module_ids = {f"{module.name}.{model.name}" for model in module_models}
        collisions = module_ids & self._models.keys()
        if collisions:
            raise RegistryError(f"duplicate model resource(s): {sorted(collisions)!r}")
        pending_tables: set[str] = set()
        for model in module_models:
            owner = self._tables.get(model.table)
            if owner is not None or model.table in pending_tables:
                owner_name = owner or module.name
                raise RegistryError(
                    f"table {model.table!r} is already owned by model {owner_name!r}"
                )
            pending_tables.add(model.table)

        self._modules[module.name] = module
        for model in module_models:
            self._all_models[model.resource] = model
            if model.name in module.exports:
                self._models[model.resource] = model
            self._tables[model.table] = model.resource

    def get_model(self, resource: str) -> ModelDefinition:
        try:
            return self._models[resource]
        except KeyError as exc:
            raise RegistryError(f"model {resource!r} is not registered or public") from exc

    def get_model_any(self, resource: str) -> ModelDefinition:
        try:
            return self._all_models[resource]
        except KeyError as exc:
            raise RegistryError(f"model {resource!r} is not registered") from exc


def load_module(path: str | Path) -> ModuleDefinition:
    source = Path(path)
    try:
        raw = yaml.load(source.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except (OSError, yaml.YAMLError) as exc:
        raise SchemaError(f"{source}: {exc}") from exc
    return parse_module(raw, source=source)


def parse_module(raw: object, *, source: str | Path | None = None) -> ModuleDefinition:
    location = str(source) if source else "<module>"
    if not isinstance(raw, dict):
        raise SchemaError(f"{location}: module root must be a mapping")
    _keys(
        raw,
        {"version", "name", "module_version", "requires", "exports", "models_path"},
        location,
    )
    if raw.get("version") != 1:
        raise SchemaError(f"{location}: version must be 1")
    name = _identifier(raw.get("name"), "name", location)
    try:
        version = Version(str(raw.get("module_version")))
    except InvalidVersion as exc:
        raise SchemaError(f"{location}: module_version must be valid PEP 440") from exc

    requires_raw = raw.get("requires", [])
    if not isinstance(requires_raw, list):
        raise SchemaError(f"{location}: requires must be a list")
    dependencies = []
    seen = set()
    for item in requires_raw:
        if not isinstance(item, dict):
            raise SchemaError(f"{location}: each dependency must be a mapping")
        _keys(item, {"name", "version"}, location)
        dep_name = _identifier(item.get("name"), "dependency name", location)
        specifier = item.get("version")
        if not isinstance(specifier, str):
            raise SchemaError(f"{location}: dependency {dep_name!r} requires a version range")
        try:
            spec = SpecifierSet(specifier)
        except InvalidSpecifier as exc:
            raise SchemaError(f"{location}: invalid version range {specifier!r}") from exc
        if dep_name in seen:
            raise SchemaError(f"{location}: duplicate dependency {dep_name!r}")
        seen.add(dep_name)
        dependencies.append(ModuleDependency(dep_name, str(spec)))

    exports_raw = raw.get("exports")
    if not isinstance(exports_raw, dict):
        raise SchemaError(f"{location}: exports must be a mapping")
    _keys(exports_raw, {"models"}, location)
    exports = exports_raw.get("models")
    if not isinstance(exports, list) or not all(isinstance(v, str) for v in exports):
        raise SchemaError(f"{location}: exports.models must be a string list")
    if len(set(exports)) != len(exports):
        raise SchemaError(f"{location}: exports.models contains duplicates")
    for model_name in exports:
        _identifier(model_name, "exported model", location, upper=True)

    models_path = raw.get("models_path", "models")
    if not isinstance(models_path, str) or not models_path or models_path.startswith("/"):
        raise SchemaError(f"{location}: models_path must be a non-empty relative path")
    if ".." in Path(models_path).parts:
        raise SchemaError(f"{location}: models_path must not escape the module directory")

    return ModuleDefinition(
        name=name,
        version=version,
        requires=tuple(dependencies),
        exports=tuple(exports),
        models_path=models_path,
        source=Path(source) if source else None,
    )
