from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID


class Invoice:
    __tablename__ = "sales_invoice"
    __resource__ = "sales.Invoice"

    number: str
    status: str
    total: Decimal
    id: UUID
    created_at: datetime
    updated_at: datetime

    __fields__ = (
        "number",
        "status",
        "total",
        "id",
        "created_at",
        "updated_at",
    )

import yaml

_EMBEDDED_MODEL = yaml.safe_load('version: 1\nmodule: sales\nmodel: Invoice\nmixins:\n  - uuid_pk\n  - timestamps\nfields:\n  number:\n    type: text\n    required: true\n  status:\n    type: enum\n    values: [draft, submitted, paid, void]\n    required: true\n    default: draft\n  total:\n    type: decimal\n    required: true\n    default: 0\nrelations:\n  customer:\n    type: many_to_one\n    target: sales.Customer\n    required: true\n    on_delete: restrict\n  lines:\n    type: one_to_many\n    target: sales.InvoiceLine\n    mapped_by: invoice\nconstraints:\n  unique:\n    - [number]\n  check:\n    - field: total\n      op: gte\n      value: 0\n')


def definition():
    from keelmodel.schema import parse_model

    return parse_model(_EMBEDDED_MODEL)


def build_model(resolve, dialect: str = "postgresql"):
    # Build the live SQLAlchemy class for this definition via map_model.
    # `resolve` maps resource names (e.g. 'sales.Customer') to their mapped
    # classes - KeelModel already exposes this to generated code.
    from keelmodel.runtime.models import map_model

    return map_model(definition(), resolve, dialect)

