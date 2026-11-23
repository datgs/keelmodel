from __future__ import annotations

from datetime import datetime
from uuid import UUID


class Customer:
    __tablename__ = "sales_customer"
    __resource__ = "sales.Customer"

    name: str
    email: str | None
    id: UUID
    created_at: datetime
    updated_at: datetime

    __fields__ = (
        "name",
        "email",
        "id",
        "created_at",
        "updated_at",
    )
