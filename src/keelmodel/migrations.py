from __future__ import annotations

from pathlib import Path
from typing import Any

from keelmodel.schema import ModelDefinition


def generate_migration_draft(
    definitions: list[ModelDefinition],
    output_path: str | Path,
    revision: str = "0001",
    down_revision: str | None = None,
    resolve: Any = None,
) -> Path:
    """Generate a reviewable Alembic migration draft.

    Emits a standard revision file with upgrade()/downgrade() including
    FK columns for many_to_one/one_to_one relations (resolved via
    `resolve(resource) -> ModelDefinition` when relations are present).
    The draft never executes against a database.
    """
    if any(d.relations for d in definitions) and resolve is None:
        raise ValueError("migrations for related models require a resolver")
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        '"""Auto-generated migration draft for KeelModel. Review before applying."""',
        "",
        "from alembic import op",
        "import sqlalchemy as sa",
        "",
        f"revision = {revision!r}",
        f"down_revision = {down_revision!r}",
        "branch_labels = None",
        "depends_on = None",
        "",
        "",
        "def upgrade() -> None:",
    ]
    for defn in definitions:
        lines.append(f'    op.create_table("{defn.table}",')
        for field in defn.fields:
            lines.append(f"        {_column_spec(field)},")
        for rel in defn.relations:
            if rel.kind == "one_to_many":
                continue
            target = resolve(rel.target)
            pk = next(f for f in target.fields if f.primary_key)
            fk_name = f"{rel.name}_id"
            on_delete = {
                "restrict": "RESTRICT",
                "cascade": "CASCADE",
                "set_null": "SET NULL",
            }[rel.on_delete]
            lines.append(
                f'        sa.Column("{fk_name}", {_sa_type_string(pk.type)}, '
                f'sa.ForeignKey("{target.table}.{pk.name}", ondelete="{on_delete}"), '
                f"nullable={not rel.required}),"
            )
        for group in defn.uniques:
            cols = ", ".join(repr(c) for c in group)
            lines.append(f"        sa.UniqueConstraint({cols}),")
        lines.append("    )")
        for group in defn.indexes:
            cols = ", ".join(repr(c) for c in group)
            lines.append(
                f'    op.create_index("{defn.table}_{"_".join(group)}_idx", '
                f"{defn.table!r}, [{cols}])"
            )
    if not definitions:
        lines.append("    pass")
    lines.append("")
    lines.append("")
    lines.append("def downgrade() -> None:")
    for defn in reversed(definitions):
        lines.append(f'    op.drop_table("{defn.table}")')
    if not definitions:
        lines.append("    pass")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _column_spec(field: Any) -> str:
    nullable = "False" if field.required else "True"
    pk = "True" if field.primary_key else "False"
    sa_type = _sa_type_string(field.type, field)
    default = ""
    if field.default is not None:
        if field.default == "current_timestamp":
            default = ', server_default=sa.text("CURRENT_TIMESTAMP")'
        elif field.default == "uuid4":
            default = ""
        elif isinstance(field.default, str):
            default = f", server_default={field.default!r}"
        else:
            default = f", server_default={field.default!r}"
    return (
        f'sa.Column("{field.name}", {sa_type}, nullable={nullable}, '
        f"primary_key={pk}{default})"
    )


def _sa_type_string(field_type: str, field: Any = None) -> str:
    length = getattr(field, "length", None)
    if length is not None:
        return f"sa.String({length})"
    return {
        "uuid": "sa.Uuid()",
        "text": "sa.Text()",
        "integer": "sa.Integer()",
        "decimal": "sa.Numeric()",
        "boolean": "sa.Boolean()",
        "date": "sa.Date()",
        "datetime": "sa.DateTime(timezone=True)",
        "bytes": "sa.LargeBinary()",
        "enum": "sa.Text()",
        "json": "sa.JSON()",
        "url": "sa.Text()",
        "file_reference": "sa.dialects.postgresql.JSONB()",
        "location": "sa.dialects.postgresql.JSONB()",
    }[field_type]
