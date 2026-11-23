import pytest

from keelpolicy.evaluator import evaluate
from keelpolicy.parser import PolicyError, parse_policy
from keelpolicy.types import Decision, PolicyRequest


def test_parse_policy_rejects_invalid():
    with pytest.raises(PolicyError):
        parse_policy({})
    with pytest.raises(PolicyError):
        parse_policy({"version": 1})
    with pytest.raises(PolicyError):
        parse_policy({"version": 1, "statements": []})


def test_evaluate_default_deny():
    stmt = {
        "effect": "allow",
        "actions": ["read"],
        "resources": ["sales.Invoice"],
        "subjects": ["role:admin"],
    }
    req = PolicyRequest(
        action="read",
        resource="sales.Invoice",
        subject={"roles": ["viewer"]},
        attributes={},
    )
    decision = evaluate([stmt], req)
    assert decision.decision == Decision.DENY


def test_evaluate_allow_by_role():
    stmt = {
        "effect": "allow",
        "actions": ["read"],
        "resources": ["sales.Invoice"],
        "subjects": ["role:admin"],
    }
    req = PolicyRequest(
        action="read",
        resource="sales.Invoice",
        subject={"roles": ["admin"]},
        attributes={},
    )
    decision = evaluate([stmt], req)
    assert decision.decision == Decision.ALLOW


def test_evaluate_deny_overrides():
    stmts = [
        {
            "effect": "allow",
            "actions": ["read"],
            "resources": ["*"],
            "subjects": ["*"],
        },
        {
            "effect": "deny",
            "actions": ["read"],
            "resources": ["sales.Invoice"],
            "subjects": ["*"],
        },
    ]
    req = PolicyRequest(
        action="read",
        resource="sales.Invoice",
        subject={},
        attributes={},
    )
    decision = evaluate(stmts, req)
    assert decision.decision == Decision.DENY


def test_evaluate_record_condition():
    stmt = {
        "effect": "allow",
        "actions": ["read"],
        "resources": ["sales.Invoice"],
        "subjects": ["role:sales"],
        "condition": {"field": "record.owner_id", "op": "eq", "value": 42},
    }
    req = PolicyRequest(
        action="read",
        resource="sales.Invoice",
        subject={"roles": ["sales"]},
        attributes={},
        record={"owner_id": 42},
    )
    decision = evaluate([stmt], req)
    assert decision.decision == Decision.ALLOW

    req2 = PolicyRequest(
        action="read",
        resource="sales.Invoice",
        subject={"roles": ["sales"]},
        attributes={},
        record={"owner_id": 99},
    )
    decision2 = evaluate([stmt], req2)
    assert decision2.decision == Decision.DENY
