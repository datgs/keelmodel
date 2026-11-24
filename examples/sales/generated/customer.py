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

import yaml

_EMBEDDED_MODEL = yaml.safe_load('version: 1\nmodule: sales\nmodel: Customer\nmixins:\n  - uuid_pk\n  - timestamps\nfields:\n  name:\n    type: text\n    required: true\n  email:\n    type: url\nconstraints:\n  unique:\n    - [email]\n')


def definition():
    from keelmodel.schema import parse_model

    return parse_model(_EMBEDDED_MODEL)


def build_model(resolve, dialect: str = "postgresql"):
    # Build the live SQLAlchemy class for this definition via map_model.
    # `resolve` maps resource names (e.g. 'sales.Customer') to their mapped
    # classes - KeelModel already exposes this to generated code.
    from keelmodel.runtime.models import map_model

    return map_model(definition(), resolve, dialect)

