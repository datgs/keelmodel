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
