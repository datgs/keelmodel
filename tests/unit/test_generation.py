from pathlib import Path

from keelmodel.generation import generate_model, render_model
from keelmodel.schema import parse_model


def test_render_model_is_deterministic_and_typed():
    model = parse_model(
        {
            "version": 1,
            "module": "sales",
            "model": "Invoice",
            "fields": {
                "id": {"type": "uuid", "primary_key": True},
                "total": {"type": "decimal", "required": True},
                "note": {"type": "text"},
            },
        }
    )

    first = render_model(model)
    second = render_model(model)
    assert first == second
    assert "class Invoice:" in first
    assert "total: Decimal" in first
    assert "note: str | None" in first
    compile(first, "invoice.py", "exec")


def test_generation_is_byte_deterministic(tmp_path: Path):
    first = generate_model("examples/sales/models/invoice.yaml", tmp_path)
    content = first.read_bytes()
    second = generate_model("examples/sales/models/invoice.yaml", tmp_path)
    assert first == second
    assert second.read_bytes() == content
