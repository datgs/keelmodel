from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from keelmodel.authz import AuthorizationProvider
from keelmodel.registry import ModuleRegistry, RegistryError
from keelmodel.runtime.context import OperationContext
from keelmodel.runtime.errors import (
    ConflictError,
    NotFoundError,
    PermissionDenied,
    PersistenceError,
    ValidationError,
)
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
        if self.engine.dialect.name == "sqlite":
            from sqlalchemy import event

            @event.listens_for(self.engine, "connect")
            def _fk_pragma(dbapi_conn: Any, _record: Any) -> None:
                dbapi_conn.execute("PRAGMA foreign_keys=ON")

        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)
        if audit is not None:
            audit.install(self.session_factory)
        self._tx = threading.local()
        self._models: dict[str, Any] = {}
        self._definitions: dict[str, ModelDefinition] = {}
        self._all_mapped: dict[str, Any] = {}
        for module in registry.modules:
            for model_name in module.exports:
                resource = f"{module.name}.{model_name}"
                definition = registry.get_model(resource)
                self._definitions[resource] = definition
        all_defs = {
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
                self._commit(session)
            except IntegrityError as exc:
                raise ConflictError(f"failed to create {resource}: {exc.orig}") from exc
            allowed = self._read_allowed_columns(resource, context, model)
            session.refresh(instance, attribute_names=sorted(allowed) if allowed else None)
            return self._project(
                model, instance, resource=resource, context=context,
                allowed=allowed,
            )

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
        coercer = self._field_coercer(definition)
        allowed = self._read_allowed_columns(resource, context, model)
        with self._session(context) as session:
            instance = self._fetch(
                session, model, definition, key, coercer, allowed
            )
            if instance is None:
                raise NotFoundError(f"{resource} {key!r} was not found")
            if self.authz and not self.authz.record_allowed(
                Operation.READ, resource, context, instance,
                allowed_columns=allowed,
            ):
                raise PermissionDenied(f"read on {resource} {key!r}: record-level deny")
            return self._project(
                model, instance, include_private=include_private,
                resource=resource, context=context, allowed=allowed,
            )

    def update(
        self, resource: str, key: Any, changes: dict[str, Any], context: OperationContext
    ) -> Any:
        if self.authz:
            self.authz.check(Operation.UPDATE, resource, context)
            changes = self.authz.filter_fields(Operation.UPDATE, resource, context, changes)
        model = self._model(resource)
        definition = self._definition(resource)
        coercer = self._field_coercer(definition)
        allowed = self._read_allowed_columns(resource, context, model)
        with self._session(context) as session:
            instance = self._fetch(
                session, model, definition, key, coercer, allowed
            )
            if instance is None:
                raise NotFoundError(f"{resource} {key!r} was not found")
            if self.authz and not self.authz.record_allowed(
                Operation.UPDATE, resource, context, instance,
                allowed_columns=allowed,
            ):
                raise PermissionDenied(f"update on {resource} {key!r}: record-level deny")
            self._assign(instance, definition, changes)
            try:
                self._commit(session)
            except IntegrityError as exc:
                raise ConflictError(f"failed to update {resource}: {exc.orig}") from exc
            session.refresh(instance, attribute_names=sorted(allowed) if allowed else None)
            return self._project(
                model, instance, resource=resource, context=context,
                allowed=allowed,
            )

    def delete(self, resource: str, key: Any, context: OperationContext) -> None:
        if self.authz:
            self.authz.check(Operation.DELETE, resource, context)
        model = self._model(resource)
        definition = self._definition(resource)
        coercer = self._field_coercer(definition)
        allowed = self._read_allowed_columns(resource, context, model)
        with self._session(context) as session:
            instance = self._fetch(
                session, model, definition, key, coercer, allowed
            )
            if instance is None:
                raise NotFoundError(f"{resource} {key!r} was not found")
            if self.authz and not self.authz.record_allowed(
                Operation.DELETE, resource, context, instance,
                allowed_columns=allowed,
            ):
                raise PermissionDenied(f"delete on {resource} {key!r}: record-level deny")
            session.delete(instance)
            try:
                self._commit(session)
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
        model = self._model(resource)
        definition = self._definition(resource)
        allowed = self._read_allowed_columns(resource, context, model)
        self._check_field_capability(
            resource, context, "filter", _filter_fields(filters)
        )
        self._check_field_capability(
            resource, context, "order", [o.lstrip("-") for o in order or []]
        )
        statement = select(model)
        count_statement = select(func.count()).select_from(model)
        if allowed is not None:
            from sqlalchemy.orm import load_only

            statement = statement.options(
                load_only(*[getattr(model, c) for c in allowed])
            )
        if self.authz:
            authz_filter = self.authz.record_filter(
                resource, context, model, self._field_coercer(definition)
            )
            if authz_filter is not None:
                statement = statement.where(authz_filter)
                count_statement = count_statement.where(authz_filter)
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
        return Page(
            tuple(
                self._project(
                    model, row, resource=resource, context=context,
                    allowed=allowed,
                )
                for row in rows
            ),
            total,
            limit,
            offset,
        )

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
                self._commit(session)
            except IntegrityError as exc:
                raise ConflictError(f"failed bulk create for {resource}: {exc.orig}") from exc
            return tuple(self._project(model, instance) for instance in instances)

    @contextmanager
    def transaction(self, context: OperationContext | None = None) -> Any:
        """Shared atomic transaction: ops inside commit together, or all roll back."""
        if getattr(self._tx, "session", None) is not None:
            raise PersistenceError("nested transactions are not supported")
        session: Session = self.session_factory()
        if context is not None:
            session.info["keelmodel_context"] = context
        self._tx.session = session
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            self._tx.session = None
            session.close()

    def _fetch(
        self,
        session: Session,
        model: Any,
        definition: ModelDefinition,
        key: Any,
        coercer: Any,
        allowed: set[str] | None = None,
    ) -> Any:
        pk_fields = definition.primary_key_fields
        pk_value = (
            coercer(pk_fields[0], key)
            if len(pk_fields) == 1
            else self._composite_key(pk_fields, key, coercer)
        )
        if allowed is None:
            return session.get(model, pk_value)
        # Read-denied columns must not be selected into memory.
        from sqlalchemy.orm import load_only

        pk_values = pk_value if isinstance(pk_value, tuple) else (pk_value,)
        where = [
            getattr(model, name) == value
            for name, value in zip(pk_fields, pk_values)
        ]
        stmt = select(model).where(*where).options(
            load_only(*[getattr(model, c) for c in allowed])
        )
        return session.scalars(stmt).first()

    def _commit(self, session: Session) -> None:
        try:
            if session is getattr(self._tx, "session", None):
                session.flush()
            else:
                session.commit()
        except IntegrityError:
            raise
        except OperationalError as exc:
            # MySQL reports CHECK violations as OperationalError (3819),
            # not IntegrityError — normalize to the same contract.
            if _is_check_violation(exc):
                raise ConflictError(f"check constraint violated: {exc.orig}") from exc
            raise

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

    def _read_allowed_columns(
        self, resource: str, context: OperationContext, model: Any
    ) -> set[str] | None:
        """Columns allowed to reach application memory, or None for all.
        Read-denied fields are never selected (contract §6)."""
        if not self.authz:
            return None
        denied = self.authz.field_capability(
            resource, context, "read", Operation.READ
        )
        if not denied:
            return None
        return {c.name for c in model.__table__.columns if c.name not in denied}

    def _check_field_capability(
        self,
        resource: str,
        context: OperationContext,
        mode: str,
        fields: list[str],
    ) -> None:
        if not fields or not self.authz:
            return
        denied = self.authz.field_capability(
            resource, context, mode, Operation.QUERY
        )
        for name in fields:
            if name in denied:
                raise PermissionDenied(
                    f"query on {resource}: {mode} on field {name!r} denied"
                )

    def _project(
        self,
        model: Any,
        instance: Any,
        include_private: bool = False,
        resource: str | None = None,
        context: OperationContext | None = None,
        allowed: set[str] | None = None,
    ) -> dict[str, Any]:
        data = {
            column.name: getattr(instance, column.name)
            for column in instance.__table__.columns
            if (include_private or not column.name.startswith("_"))
            and (allowed is None or column.name in allowed)
        }
        if self.authz and resource and context:
            data = self.authz.apply_read_projection(resource, context, data)
        return data

    @contextmanager
    def _session(self, context: OperationContext | None = None) -> Any:
        bound = getattr(self._tx, "session", None)
        if bound is not None:
            if context is not None:
                bound.info["keelmodel_context"] = context
            yield bound
            return
        session: Session = self.session_factory()
        if context is not None:
            session.info["keelmodel_context"] = context
        try:
            yield session
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()


def _all_resources(registry: ModuleRegistry) -> list[str]:
    return list(registry._all_models)


def _filter_fields(expression: dict[str, Any] | None) -> list[str]:
    """Field names referenced by a filter expression (all/any recursion)."""
    if not expression:
        return []
    if set(expression) == {"all"}:
        return [f for c in expression["all"] for f in _filter_fields(c)]
    if set(expression) == {"any"}:
        return [f for c in expression["any"] for f in _filter_fields(c)]
    field = expression.get("field")
    return [field] if isinstance(field, str) else []


def _is_check_violation(exc: OperationalError) -> bool:
    orig = getattr(exc, "orig", None)
    if orig is None:
        return False
    args = getattr(orig, "args", ())
    if args and args[0] == 3819:
        return True
    return "check constraint" in str(orig).lower()
