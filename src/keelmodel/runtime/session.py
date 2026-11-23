from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from keelmodel.authz import AuthorizationProvider
from keelmodel.registry import ModuleRegistry, RegistryError
from keelmodel.runtime.context import OperationContext
from keelmodel.runtime.errors import ConflictError, NotFoundError, PersistenceError, ValidationError
from keelmodel.runtime.filtering import compile_filter_expression
from keelmodel.runtime.models import map_model, wire_relationships
from keelmodel.runtime.operations import Operation
from keelmodel.runtime.results import Page
from keelmodel.runtime.serialization import coerce_input_values, deserialize_value
from keelmodel.schema import ModelDefinition


class KeelModel:
    def __init__(
        self,
        database_url: str,
        registry: ModuleRegistry,
        authz: AuthorizationProvider | None = None,
        audit: Any | None = None,
    ) -> None:
        self.database_url = database_url
        self.registry = registry
        self.authz = authz
        self.audit = audit
        self.engine = create_engine(database_url)
        if audit is not None:
            audit.create_all(self.engine)
            audit.install()
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)
        self._models: dict[str, Any] = {}
        self._definitions: dict[str, ModelDefinition] = {}
        self._all_mapped: dict[str, Any] = {}
        for module in registry.modules:
            for model_name in module.exports:
                resource = f"{module.name}.{model_name}"
                definition = registry.get_model(resource)
                self._definitions[resource] = definition
        all_defs = {m.resource: m for m in registry.models} | {
            r: registry.get_model_any(r) for r in _all_resources(registry)
        }
        dialect = self.engine.dialect.name
        for resource, definition in all_defs.items():
            self._all_mapped[resource] = map_model(
                definition, resolve=registry.get_model_any, dialect=dialect
            )
        for resource, model_type in self._all_mapped.items():
            definition = all_defs[resource]
            if definition.relations:
                wire_relationships(
                    definition, model_type, self._all_mapped, registry.get_model_any
                )
        self._models = {
            resource: self._all_mapped[resource] for resource in self._definitions
        }
        from sqlalchemy.orm import configure_mappers

        configure_mappers()

    def create(self, resource: str, values: dict[str, Any], context: OperationContext) -> Any:
        if self.authz:
            self.authz.check(Operation.CREATE, resource, context)
            values = self.authz.filter_fields(Operation.CREATE, resource, context, values)
        model = self._model(resource)
        with self._session(context) as session:
            instance = self._construct(model, self._definition(resource), values)
            session.add(instance)
            try:
                session.commit()
            except IntegrityError as exc:
                raise ConflictError(f"failed to create {resource}: {exc.orig}") from exc
            session.refresh(instance)
            return self._project(model, instance)

    def get(
        self,
        resource: str,
        key: Any,
        context: OperationContext,
        include_private: bool = False,
    ) -> Any:
        if self.authz:
            self.authz.check(Operation.READ, resource, context)
        model = self._model(resource)
        definition = self._definition(resource)
        pk_fields = definition.primary_key_fields
        coercer = self._field_coercer(definition)
        with self._session(context) as session:
            if len(pk_fields) == 1:
                instance = session.get(model, coercer(pk_fields[0], key))
            else:
                instance = session.get(
                    model, self._composite_key(pk_fields, key, coercer)
                )
            if instance is None:
                raise NotFoundError(f"{resource} {key!r} was not found")
            return self._project(model, instance, include_private=include_private)

    def update(
        self, resource: str, key: Any, changes: dict[str, Any], context: OperationContext
    ) -> Any:
        if self.authz:
            self.authz.check(Operation.UPDATE, resource, context)
            changes = self.authz.filter_fields(Operation.UPDATE, resource, context, changes)
        model = self._model(resource)
        definition = self._definition(resource)
        pk_fields = definition.primary_key_fields
        coercer = self._field_coercer(definition)
        with self._session(context) as session:
            if len(pk_fields) == 1:
                instance = session.get(model, coercer(pk_fields[0], key))
            else:
                instance = session.get(
                    model, self._composite_key(pk_fields, key, coercer)
                )
            if instance is None:
                raise NotFoundError(f"{resource} {key!r} was not found")
            self._assign(instance, definition, changes)
            try:
                session.commit()
            except IntegrityError as exc:
                raise ConflictError(f"failed to update {resource}: {exc.orig}") from exc
            session.refresh(instance)
            return self._project(model, instance)

    def delete(self, resource: str, key: Any, context: OperationContext) -> None:
        if self.authz:
            self.authz.check(Operation.DELETE, resource, context)
        model = self._model(resource)
        definition = self._definition(resource)
        pk_fields = definition.primary_key_fields
        coercer = self._field_coercer(definition)
        with self._session(context) as session:
            if len(pk_fields) == 1:
                instance = session.get(model, coercer(pk_fields[0], key))
            else:
                instance = session.get(
                    model, self._composite_key(pk_fields, key, coercer)
                )
            if instance is None:
                raise NotFoundError(f"{resource} {key!r} was not found")
            session.delete(instance)
            try:
                session.commit()
            except IntegrityError as exc:
                raise ConflictError(f"failed to delete {resource}: {exc.orig}") from exc

    def query(
        self,
        resource: str,
        context: OperationContext,
        filters: dict[str, Any] | None = None,
        order: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page:
        if self.authz:
            self.authz.check(Operation.QUERY, resource, context)
            record_cond = self.authz.record_condition(resource, context)
            if record_cond and record_cond.get("__deny_all__"):
                from keelmodel.runtime.errors import PermissionDenied

                raise PermissionDenied(f"query on {resource}: record-level deny")
        model = self._model(resource)
        definition = self._definition(resource)
        statement = select(model)
        count_statement = select(func.count()).select_from(model)
        if filters is not None:
            try:
                condition = compile_filter_expression(
                    filters, model, coercer=self._field_coercer(definition)
                )
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
            statement = statement.where(condition)
            count_statement = count_statement.where(condition)
        if order:
            for item in order:
                descending = item.startswith("-")
                name = item[1:] if descending else item
                if not hasattr(model, name):
                    raise ValidationError(f"unknown order field {name!r}")
                column = getattr(model, name)
                statement = statement.order_by(column.desc() if descending else column.asc())
        statement = statement.limit(limit).offset(offset)
        with self._session(context) as session:
            total = session.scalar(count_statement) or 0
            rows = session.scalars(statement).all()
        return Page(tuple(self._project(model, row) for row in rows), total, limit, offset)

    def bulk(
        self, resource: str, items: list[dict[str, Any]], context: OperationContext
    ) -> tuple[Any, ...]:
        if self.authz:
            self.authz.check(Operation.BULK, resource, context)
            items = [
                self.authz.filter_fields(Operation.BULK, resource, context, item)
                for item in items
            ]
        model = self._model(resource)
        definition = self._definition(resource)
        with self._session(context) as session:
            instances = [self._construct(model, definition, values) for values in items]
            session.add_all(instances)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise ConflictError(f"failed bulk create for {resource}: {exc.orig}") from exc
            return tuple(self._project(model, instance) for instance in instances)

    @contextmanager
    def transaction(self) -> Any:
        with self._session() as session:
            yield session

    def _field_coercer(self, definition: ModelDefinition):
        fields = {f.name: f for f in definition.fields}
        fks = {
            f"{rel.name}_id": rel
            for rel in definition.relations
            if rel.kind != "one_to_many"
        }

        def coerce(name: str, value: Any) -> Any:
            field = fields.get(name)
            if field is None and name in fks:
                target = self.registry.get_model_any(fks[name].target)
                field = next(f for f in target.fields if f.primary_key)
            if field is None:
                return value
            return deserialize_value(field, value)

        return coerce

    def _model(self, resource: str) -> Any:
        try:
            return self._models[resource]
        except KeyError as exc:
            raise RegistryError(f"model {resource!r} is not registered or public") from exc

    def _definition(self, resource: str) -> ModelDefinition:
        try:
            return self._definitions[resource]
        except KeyError as exc:
            raise RegistryError(f"model {resource!r} is not registered or public") from exc

    def _composite_key(
        self, pk_fields: tuple[str, ...], key: Any, coercer: Any = None
    ) -> tuple[Any, ...]:
        raw = None
        if isinstance(key, dict):
            missing = set(pk_fields) - set(key)
            if missing:
                raise ValidationError(f"missing primary key field(s): {sorted(missing)}")
            raw = tuple(key[field] for field in pk_fields)
        elif isinstance(key, (list, tuple)) and len(key) == len(pk_fields):
            raw = tuple(key)
        if raw is None:
            raise ValidationError(
                f"composite primary key requires a mapping or tuple of {len(pk_fields)} values"
            )
        if coercer is None:
            return raw
        return tuple(coercer(name, value) for name, value in zip(pk_fields, raw))

    def _construct(self, model: Any, definition: ModelDefinition, values: dict[str, Any]) -> Any:
        fk_names = {
            f"{rel.name}_id": rel
            for rel in definition.relations
            if rel.kind != "one_to_many"
        }
        known = {field.name for field in definition.fields} | set(fk_names)
        unknown = set(values) - known
        if unknown:
            raise ValidationError(f"unknown field(s): {sorted(unknown)}")
        field_values = {k: v for k, v in values.items() if k not in fk_names}
        coerced = coerce_input_values(definition, field_values)
        for fk_name, rel in fk_names.items():
            if fk_name in values:
                target = self.registry.get_model_any(rel.target)
                pk = next(f for f in target.fields if f.primary_key)
                coerced[fk_name] = deserialize_value(pk, values[fk_name])
        return model(**coerced)

    def _assign(self, instance: Any, definition: ModelDefinition, changes: dict[str, Any]) -> None:
        fk_names = {
            f"{rel.name}_id": rel
            for rel in definition.relations
            if rel.kind != "one_to_many"
        }
        fields = {field.name: field for field in definition.fields}
        for name, value in changes.items():
            field = fields.get(name)
            if field is None and name in fk_names:
                target = self.registry.get_model_any(fk_names[name].target)
                field = next(f for f in target.fields if f.primary_key)
            if field is None:
                raise ValidationError(f"unknown field {name!r} for {definition.resource}")
            if field.primary_key:
                raise ValidationError(f"primary key field {name!r} cannot be updated")
            setattr(instance, name, deserialize_value(field, value))

    def _project(self, model: Any, instance: Any, include_private: bool = False) -> dict[str, Any]:
        if not include_private:
            return {
                column.name: getattr(instance, column.name)
                for column in instance.__table__.columns
                if not column.name.startswith("_")
            }
        return {
            column.name: getattr(instance, column.name)
            for column in instance.__table__.columns
        }

    @contextmanager
    def _session(
        self, context: OperationContext | None = None
    ) -> Any:
        session: Session = self.session_factory()
        if context is not None:
            session.info["keelmodel_context"] = context
        try:
            yield session
        except (ValidationError, ConflictError, NotFoundError, PersistenceError):
            session.rollback()
            raise
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def _all_resources(registry: ModuleRegistry) -> list[str]:
    return list(registry._all_models)
