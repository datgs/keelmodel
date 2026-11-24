from __future__ import annotations

from typing import Any

from keelpolicy.types import Decision, PolicyDecision, PolicyRequest


def evaluate(statements: list[dict[str, Any]], request: PolicyRequest) -> PolicyDecision:
    """Deny-overrides evaluation. Deny statements take precedence over allows."""
    allow_match = None
    for stmt in statements:
        if not _matches(stmt, request):
            continue
        if stmt["effect"] == "deny":
            return PolicyDecision(
                decision=Decision.DENY,
                reason=stmt.get("reason", "explicit deny"),
                condition=stmt.get("condition"),
            )
        if allow_match is None:
            allow_match = stmt
    if allow_match is not None:
        return PolicyDecision(
            decision=Decision.ALLOW,
            reason=allow_match.get("reason"),
            condition=allow_match.get("condition"),
        )
    return PolicyDecision(decision=Decision.DENY, reason="default deny")


def _matches(stmt: dict[str, Any], request: PolicyRequest) -> bool:
    if request.action not in stmt["actions"] and "*" not in stmt["actions"]:
        return False
    if not _resource_matches(stmt["resources"], request.resource):
        return False
    if not _subject_matches(stmt["subjects"], request.subject):
        return False
    if stmt.get("condition") is not None:
        return _eval_condition(stmt["condition"], request)
    return True


def _resource_matches(patterns: list[str], resource: str) -> bool:
    for pattern in patterns:
        if pattern == "*":
            return True
        if pattern.endswith("*") and resource.startswith(pattern[:-1]):
            return True
        if pattern == resource:
            return True
    return False


def _subject_matches(subjects: list[str], subject: dict[str, Any]) -> bool:
    roles = subject.get("roles", ())
    if isinstance(roles, str):
        roles = (roles,)
    if not isinstance(roles, (list, tuple, set)):
        roles = ()
    for pattern in subjects:
        if pattern == "*":
            return True
        if pattern.startswith("role:") and pattern[5:] in roles:
            return True
    return False


def _eval_condition(condition: dict[str, Any], request: PolicyRequest) -> bool:
    if set(condition) == {"all"}:
        return all(_eval_condition(c, request) for c in condition["all"])
    if set(condition) == {"any"}:
        return any(_eval_condition(c, request) for c in condition["any"])
    if set(condition) == {"field", "op", "value"}:
        return _eval_field_op(condition, request)
    return False


def _eval_field_op(condition: dict[str, Any], request: PolicyRequest) -> bool:
    field = condition["field"]
    op = condition["op"]
    expected = condition["value"]

    actual = _resolve_field(field, request)
    if op == "is_null":
        return (actual is None) == bool(expected)
    if actual is None:
        return False
    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual != expected
    if op == "in":
        return isinstance(expected, (list, tuple)) and actual in expected
    if op == "contains":
        return expected in actual
    if op == "lt":
        return actual < expected
    if op == "lte":
        return actual <= expected
    if op == "gt":
        return actual > expected
    if op == "gte":
        return actual >= expected
    return False


def _resolve_field(field: str, request: PolicyRequest) -> Any:
    if field.startswith("subject."):
        return request.subject.get(field[8:])
    if field.startswith("attributes."):
        return request.attributes.get(field[11:])
    if field.startswith("record.") and request.record is not None:
        return request.record.get(field[7:])
    return None
