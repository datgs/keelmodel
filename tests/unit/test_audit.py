from unittest.mock import MagicMock

from keelmodel.extensions.audit import AuditExtension
from keelmodel.extensions.audit.audit import AuditEntry
from keelmodel.runtime.models import map_model
from keelmodel.schema import parse_model


def _mapped_instance(resource_table="audit_invoice"):
    model = parse_model(
        {
            "version": 1,
            "module": "audit",
            "model": "AuditInvoice",
            "table": resource_table,
            "fields": {
                "id": {"type": "uuid", "primary_key": True},
                "name": {"type": "text"},
            },
        }
    )
    cls = map_model(model)
    return cls(name="test")


def test_audit_records_create_with_subject():
    audit = AuditExtension()
    session = MagicMock()
    session.info = {"keelmodel_context": MagicMock(subject={"roles": ["admin"]})}
    session.new = [_mapped_instance("audit_invoice_create")]
    session.dirty = set()
    session.deleted = set()
    session.is_modified = MagicMock(return_value=False)

    audit._before_flush(session, None, None)

    added = [c.args[0] for c in session.add.call_args_list if c.args]
    entry = next(a for a in added if isinstance(a, AuditEntry))
    assert entry.operation == "create"
    assert entry.resource == "audit.AuditInvoice"
    assert entry.subject == {"roles": ["admin"]}
    assert "name" in entry.changes


def test_audit_redacts_sensitive_fields():
    audit = AuditExtension(redact_fields={"name"})
    session = MagicMock()
    session.info = {}
    session.new = [_mapped_instance("audit_invoice_redact")]
    session.dirty = set()
    session.deleted = set()
    session.is_modified = MagicMock(return_value=False)

    audit._before_flush(session, None, None)
    entry = next(
        a for a in (c.args[0] for c in session.add.call_args_list) if isinstance(a, AuditEntry)
    )
    assert entry.changes["name"]["new"] == "[redacted]"


def test_audit_ignores_non_keelmodel_instances():
    audit = AuditExtension()
    session = MagicMock()
    session.info = {}
    session.new = [object()]
    session.dirty = set()
    session.deleted = set()
    session.is_modified = MagicMock(return_value=False)

    audit._before_flush(session, None, None)
    session.add.assert_not_called()
