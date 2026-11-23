from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import MetaData

from keelmodel.schema import ModelDefinition


def generate_migration_draft(
    definitions: list[ModelDefinition],
    output_path: str | Path,
    previous_metadata: MetaData | None = None,
) -> Path:
    """Generate a reviewable Alembic migration draft.

    The draft is a Python file with `upgrade()` and `downgrade()` stubs.
    It does not execute against the database.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    tables = []
    for defn in definitions:
        cols = []
        for field in defn.fields:
            col = _column_spec(field)
            cols.append(col)
        tables.append((defn.table, cols))

    lines = [
        '"""Auto-generated migration draft for KeelModel."""',
        "",
        "from alembic import op",
        "import sqlalchemy as sa",
        "",
        "def upgrade() -> None:",
    ]
    for table_name, cols in tables:
        lines.append(f'    op.create_table("{table_name}",')
        for col in cols:
            lines.append(f"        {col},")
        lines.append("    )")
        if not cols:
            lines.append("        pass")
    lines.append("")
    lines.append("")
    lines.append("def downgrade() -> None:")
    for table_name, _ in reversed(tables):
        lines.append(f'    op.drop_table("{table_name}")')
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _column_spec(field: Any) -> str:
    nullable = "False" if field.required else "True"
    pk = "True" if field.primary_key else "False"
    sa_type = _sa_type_string(field.type)
    default = ""
    if field.default is not None:
        if field.default == "current_timestamp":
            default = ', server_default=sa.text("CURRENT_TIMESTAMP")'
        elif isinstance(field.default, str):
            default = f', server_default=sa.text("{field.default}")'
        else:
            default = f", server_default={field.default!r}"
    return (
        f'sa.Column("{field.name}", {sa_type}, nullable={nullable}, '
        f'primary_key={pk}{default})'
    )


def _sa_type_string(field_type: str) -> str:
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
