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
