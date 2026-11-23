from __future__ import annotations

from typing import Any

from keelmodel.runtime.context import OperationContext
from keelmodel.runtime.errors import ConfigurationError, PermissionDenied
from keelmodel.runtime.operations import Operation
from keelpolicy.evaluator import evaluate
from keelpolicy.parser import load_policy
from keelpolicy.types import Decision, PolicyRequest


class AuthorizationProvider:
    """Optional field-level and record-level authorization via keelpolicy.

    If a policy file uses field rules but the app has not enabled
    field-level authorization, evaluation fails closed.
    """

    def __init__(self, policy_path: str, enable_field_rules: bool = False) -> None:
        self.statements = load_policy(policy_path)
        self.enable_field_rules = enable_field_rules

    def check(self, operation: Operation, resource: str, context: OperationContext) -> None:
        request = PolicyRequest(
            action=operation.value,
            resource=resource,
            subject=context.subject,
            attributes=context.attributes,
        )
        decision = evaluate(self.statements, request)
        if decision.decision == Decision.DENY:
            raise PermissionDenied(f"{operation.value} on {resource}: {decision.reason}")

    def filter_fields(
        self, operation: Operation, resource: str, context: OperationContext, data: dict[str, Any]
    ) -> dict[str, Any]:
        if not self.enable_field_rules:
            return data
        for stmt in self.statements:
            field_rules = stmt.get("fields")
            if field_rules is None:
                continue
            for field_name, allowed in field_rules.items():
                if field_name in data and not allowed:
                    raise ConfigurationError(
                        f"field {field_name!r} is protected but field-level auth is not enabled"
                    )
        return data

    def record_condition(self, resource: str, context: OperationContext) -> dict[str, Any] | None:
        request = PolicyRequest(
            action="query",
            resource=resource,
            subject=context.subject,
            attributes=context.attributes,
        )
        decision = evaluate(self.statements, request)
        if decision.decision == Decision.DENY:
            return {"__deny_all__": True}
        return decision.condition
