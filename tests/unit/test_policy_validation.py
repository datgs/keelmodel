"""keelpolicy parse-time validation + field-level auth enforcement."""

import pytest
import yaml

from keelmodel.authz import AuthorizationProvider
from keelmodel.runtime.context import OperationContext
from keelmodel.runtime.errors import PermissionDenied
from keelmodel.runtime.operations import Operation
from keelpolicy.parser import PolicyError, parse_policy

CTX = OperationContext(subject={"roles": ["staff"]}, attributes={})


def _policy(tmp_path, statements):
    path = tmp_path / "pol.yaml"
    path.write_text(yaml.dump({"version": 1, "statements": statements}))
    return str(path)


def _base_stmt(**extra):
    stmt = {
        "effect": "allow",
        "actions": ["*"],
        "resources": ["m.*"],
        "subjects": ["role:staff"],
    }
    stmt.update(extra)
    return stmt


def test_invalid_op_rejected():
    with pytest.raises(PolicyError, match="unknown op"):
        parse_policy(
            {
                "version": 1,
                "statements": [
                    _base_stmt(
                        condition={"field": "record.x", "op": "bogus", "value": 1}
                    )
                ],
            }
        )


def test_in_requires_list():
    with pytest.raises(PolicyError, match="requires a list"):
        parse_policy(
            {
                "version": 1,
                "statements": [
                    _base_stmt(
                        condition={"field": "record.x", "op": "in", "value": "abc"}
                    )
                ],
            }
        )


def test_bad_field_prefix_rejected():
    with pytest.raises(PolicyError, match="record.x"):
        parse_policy(
            {
                "version": 1,
                "statements": [
                    _base_stmt(
                        condition={"field": "bogus.x", "op": "eq", "value": 1}
                    )
                ],
            }
        )


def test_fields_spec_validated():
    with pytest.raises(PolicyError, match="read/write booleans"):
        parse_policy(
            {
                "version": 1,
                "statements": [
                    _base_stmt(fields={"secret": {"bogus": True}})
                ],
            }
        )


def test_field_read_projection(tmp_path):
    provider = AuthorizationProvider(
        _policy(
            tmp_path,
            [
                _base_stmt(fields={"secret": {"read": False}}),
            ],
        ),
        enable_field_rules=True,
    )
    data = {"name": "ok", "secret": "hidden"}
    result = provider.apply_read_projection("m.Doc", CTX, data)
    assert result == {"name": "ok"}


def test_field_write_denied(tmp_path):
    provider = AuthorizationProvider(
        _policy(
            tmp_path,
            [
                _base_stmt(fields={"salary": {"write": False}}),
            ],
        ),
        enable_field_rules=True,
    )
    with pytest.raises(PermissionDenied):
        provider.filter_fields(Operation.CREATE, "m.Doc", CTX, {"salary": 5})
    # Allowed field passes.
    provider.filter_fields(Operation.CREATE, "m.Doc", CTX, {"name": "x"})


def test_field_bool_shorthand_denies_both(tmp_path):
    provider = AuthorizationProvider(
        _policy(tmp_path, [_base_stmt(fields={"hidden": False})]),
        enable_field_rules=True,
    )
    assert provider.apply_read_projection(
        "m.Doc", CTX, {"hidden": 1, "ok": 2}
    ) == {"ok": 2}
    with pytest.raises(PermissionDenied):
        provider.filter_fields(Operation.UPDATE, "m.Doc", CTX, {"hidden": 1})
