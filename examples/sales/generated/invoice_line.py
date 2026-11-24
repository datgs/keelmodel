from __future__ import annotations

from decimal import Decimal
from uuid import UUID


class InvoiceLine:
    __tablename__ = "sales_invoice_line"
    __resource__ = "sales.InvoiceLine"

    description: str
    quantity: int
    unit_price: Decimal
    id: UUID

    __fields__ = (
        "description",
        "quantity",
        "unit_price",
        "id",
    )

import yaml

_EMBEDDED_MODEL = yaml.safe_load('version: 1\nmodule: sales\nmodel: InvoiceLine\nmixins:\n  - uuid_pk\nfields:\n  description:\n    type: text\n    required: true\n  quantity:\n    type: integer\n    required: true\n    default: 1\n  unit_price:\n    type: decimal\n    required: true\nrelations:\n  invoice:\n    type: many_to_one\n    target: sales.Invoice\n    required: true\n    on_delete: cascade\nconstraints:\n  check:\n    - field: quantity\n      op: gt\n      value: 0\n')


def definition():
    from keelmodel.schema import parse_model

    return parse_model(_EMBEDDED_MODEL)


def build_model(resolve, dialect: str = "postgresql"):
    # Build the live SQLAlchemy class for this definition via map_model.
    # `resolve` maps resource names (e.g. 'sales.Customer') to their mapped
    # classes - KeelModel already exposes this to generated code.
    from keelmodel.runtime.models import map_model

    return map_model(definition(), resolve, dialect)

