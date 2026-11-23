from keelmodel.migrations import generate_migration_draft
from keelmodel.schema import parse_model


def test_generates_reviewable_draft(tmp_path):
    definition = parse_model(
        {
            "version": 1,
            "module": "sales",
            "model": "Invoice",
            "fields": {
                "id": {"type": "uuid", "primary_key": True},
                "total": {"type": "decimal", "required": True},
                "status": {"type": "enum", "values": ["draft", "paid"]},
            },
        }
    )
    path = generate_migration_draft([definition], tmp_path / "001_draft.py")
    content = path.read_text()
    assert 'op.create_table("sales_invoice"' in content
    assert 'sa.Column("id", sa.Uuid(), nullable=False, primary_key=True)' in content
    assert 'sa.Column("total", sa.Numeric(), nullable=False, primary_key=False)' in content
    assert 'op.drop_table("sales_invoice")' in content
    compile(content, str(path), "exec")
