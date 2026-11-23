from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, Text, event, inspect
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class AuditBase(DeclarativeBase):
    pass


class AuditEntry(AuditBase):
    __tablename__ = "keelmodel_audit"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    operation: Mapped[str] = mapped_column(String(16))
    resource: Mapped[str] = mapped_column(Text())
    record_key: Mapped[str | None] = mapped_column(Text(), nullable=True)
    subject: Mapped[dict] = mapped_column(JSON())
    changes: Mapped[dict] = mapped_column(JSON())


_REDACTED = "[redacted]"


class AuditExtension:
    """Same-transaction audit records for create/update/delete.

    Records (operation, resource, record_key, subject, changes) inside the
    same DB transaction as the mutation. Sensitive fields can be redacted
    via `redact_fields`.
    """

    def __init__(self, redact_fields: set[str] | None = None) -> None:
        self.redact_fields = redact_fields or set()
        self.table = AuditEntry.__table__

    def create_all(self, engine: Any) -> None:
        AuditBase.metadata.create_all(engine)

    def install(self, session_factory: Any) -> None:
        """Scope the listener to this KeelModel's session factory only."""
        event.listen(session_factory, "before_flush", self._before_flush)

    def _before_flush(self, session: Session, flush_context: Any, instances: Any) -> None:
        context = session.info.get("keelmodel_context")
        subject = dict(context.subject) if context is not None else {}
        for instance in session.new:
            resource = getattr(instance, "__resource__", None)
            if resource is None:
                continue
            self._record(session, "create", resource, instance, subject)
        for instance in session.dirty:
            resource = getattr(instance, "__resource__", None)
            if resource is None or not session.is_modified(instance):
                continue
            self._record(session, "update", resource, instance, subject)
        for instance in session.deleted:
            resource = getattr(instance, "__resource__", None)
            if resource is None:
                continue
            self._record(session, "delete", resource, instance, subject)

    def _record(
        self,
        session: Session,
        operation: str,
        resource: str,
        instance: Any,
        subject: dict,
    ) -> None:
        pk = inspect(instance.__class__).primary_key
        key_parts = [
            str(getattr(instance, col.name, None)) for col in pk
        ]
        changes = {}
        if operation != "create":
            for attr in inspect(instance).attrs:
                hist = attr.history
                if hist.has_changes() and attr.key not in pk_names(pk):
                    changes[attr.key] = {
                        "old": self._redact(attr.key, _first(hist.deleted)),
                        "new": self._redact(attr.key, _first(hist.added)),
                    }
        else:
            for col in instance.__table__.columns:
                changes[col.name] = {
                    "old": None,
                    "new": self._redact(col.name, getattr(instance, col.name, None)),
                }
        entry = AuditEntry(
            operation=operation,
            resource=resource,
            record_key="|".join(key_parts) if key_parts else None,
            subject=subject,
            changes=changes,
        )
        session.add(entry)

    def _redact(self, field_name: str, value: Any) -> Any:
        if field_name in self.redact_fields:
            return _REDACTED
        return _safe(value)


def pk_names(columns: Any) -> set[str]:
    return {col.name for col in columns}


def _first(values: Any) -> Any:
    return values[0] if values else None


def _safe(value: Any) -> Any:
    from datetime import date, datetime
    from decimal import Decimal
    from uuid import UUID

    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (UUID, Decimal, bytes)):
        return str(value)
    return value
