from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    column,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from keelmodel.runtime.base import Base
from keelmodel.runtime.constraints import compile_check_constraints
from keelmodel.schema import FieldDefinition, ModelDefinition, RelationDefinition


def _base_type(field_type: str, dialect: str) -> Any:
    if field_type in {"json", "file_reference", "location"}:
        return JSONB() if dialect == "postgresql" else JSON()
    return {
        "uuid": Uuid(as_uuid=True),
        "text": Text(),
        "integer": Integer(),
        "decimal": Numeric(),
        "boolean": Boolean(),
        "date": Date(),
        "datetime": DateTime(timezone=True),
        "bytes": LargeBinary(),
        "url": Text(),
        "enum": Text(),
    }[field_type]


def map_model(
    model: ModelDefinition,
    resolve: Callable[[str], ModelDefinition] | None = None,
    dialect: str = "postgresql",
) -> type[Base]:
    attributes: dict[str, Any] = {
        "__module__": "keelmodel.generated",
        "__tablename__": model.table,
        "__resource__": model.resource,
        "__fields__": tuple(
            list(field.name for field in model.fields)
            + [f"{rel.name}_id" for rel in model.relations if rel.kind != "one_to_many"]
        ),
        "__relations__": tuple(rel.name for rel in model.relations),
        "__keelmodel_module__": model.module,
        "__annotations__": {},
    }
    table_args = compile_check_constraints(model)
    table_args += tuple(
        CheckConstraint(column(field.name).in_(list(field.values)))
        for field in model.fields
        if field.type == "enum"
    )
    table_args += tuple(UniqueConstraint(*group) for group in model.uniques)
    table_args += tuple(
        Index(f"{model.table}_{'_'.join(group)}_idx", *group)
        for group in model.indexes
    )
    # Idempotent re-mapping: mapping the same definition twice (e.g. via a
    # generated build_model call) reuses the existing Table in shared
    # Base.metadata instead of failing on duplicate definition.
    attributes["__table_args__"] = (*table_args, {"extend_existing": True})
    for field in model.fields:
        args = [_column_type(field, dialect)]
        attributes["__annotations__"][field.name] = Mapped[Any]
        attributes[field.name] = mapped_column(
            *args,
            primary_key=field.primary_key,
            nullable=not field.required,
            default=_python_default(field),
            server_default=_server_default(field),
        )
    for relation in model.relations:
        if relation.kind == "one_to_many":
            continue
        fk_name = f"{relation.name}_id"
        if fk_name in attributes["__annotations__"]:
            raise ValueError(f"relation {relation.name!r} conflicts with field {fk_name!r}")
        if resolve is None:
            raise ValueError("relations require a model resolver")
        target = resolve(relation.target)
        target_pk = [f for f in target.fields if f.primary_key]
        if len(target_pk) != 1:
            raise ValueError(
                f"relation {relation.name!r} target {relation.target!r} "
                "must have exactly one primary key"
            )
        target_pk_field = target_pk[0]
        on_delete = {
            "restrict": "RESTRICT",
            "cascade": "CASCADE",
            "set_null": "SET NULL",
        }[relation.on_delete]
        cyclic = target.resource != model.resource and any(
            r.kind != "one_to_many" and r.target == model.resource
            for r in target.relations
        )
        attributes["__annotations__"][fk_name] = Mapped[Any]
        attributes[fk_name] = mapped_column(
            _base_type(target_pk_field.type, dialect),
            ForeignKey(
                f"{target.table}.{target_pk_field.name}",
                ondelete=on_delete,
                name=f"{model.table}_{fk_name}_fkey",
                use_alter=cyclic,
            ),
            unique=(relation.kind == "one_to_one"),
            nullable=not relation.required,
        )
    model_type = type(f"{model.module}_{model.name}", (Base,), attributes)
    return model_type


def wire_relationships(
    model: ModelDefinition,
    model_type: type[Base],
    mapped: dict[str, type[Base]],
    resolver: Callable[[str], ModelDefinition],
) -> None:
    from sqlalchemy.orm import relationship

    for relation in model.relations:
        if relation.name in model_type.__dict__:
            continue
        target_type = mapped.get(relation.target)
        if target_type is None:
            continue
        if relation.kind == "one_to_many":
            if not relation.mapped_by:
                raise ValueError(
                    f"one_to_many relation {relation.name!r} requires mapped_by"
                )
            remote = resolver(relation.target)
            if not any(
                r.name == relation.mapped_by
                and r.target == model.resource
                and r.kind in {"many_to_one", "one_to_one"}
                for r in remote.relations
            ):
                raise ValueError(
                    f"one_to_many {model.resource}.{relation.name}: remote "
                    f"{relation.target}.{relation.mapped_by} does not point back"
                )
            fk_col = getattr(target_type, f"{relation.mapped_by}_id")
            setattr(
                model_type,
                relation.name,
                relationship(
                    target_type,
                    back_populates=relation.mapped_by,
                    foreign_keys=[fk_col],
                ),
            )
        else:
            fk_col = getattr(model_type, f"{relation.name}_id")
            back = _find_back_relation(relation, model, resolver)
            if back is not None:
                setattr(
                    model_type,
                    relation.name,
                    relationship(
                        target_type,
                        back_populates=back,
                        foreign_keys=[fk_col],
                    ),
                )
            else:
                setattr(
                    model_type,
                    relation.name,
                    relationship(target_type, foreign_keys=[fk_col]),
                )


def _find_back_relation(
    relation: RelationDefinition,
    model: ModelDefinition,
    resolver: Callable[[str], ModelDefinition],
) -> str | None:
    target = resolver(relation.target)
    for r in target.relations:
        if (
            r.kind == "one_to_many"
            and r.mapped_by == relation.name
            and r.target == model.resource
        ):
            return r.name
        if (
            r.kind == "one_to_one"
            and r.target == model.resource
            and relation.kind == "one_to_one"
        ):
            return r.name
    return None


def _column_type(field: FieldDefinition, dialect: str = "postgresql") -> Any:
    if field.length is not None:
        return String(field.length)
    if field.type == "enum":
        return Text()
    return _base_type(field.type, dialect)


def _python_default(field: FieldDefinition) -> Any:
    if field.default == "uuid4" and field.type == "uuid":
        return uuid4
    if field.default is not None and not (
        field.type == "datetime" and field.default == "current_timestamp"
    ):
        return field.default
    return None


def _server_default(field: FieldDefinition) -> Any:
    if field.default == "current_timestamp" and field.type == "datetime":
        return text("CURRENT_TIMESTAMP")
    return None


