from __future__ import annotations

from typing import Any

from keelmodel.runtime.context import OperationContext
from keelmodel.runtime.errors import ConfigurationError, PermissionDenied
from keelmodel.runtime.operations import Operation
from keelpolicy.evaluator import evaluate
from keelpolicy.parser import load_policy
from keelpolicy.types import Decision, PolicyRequest


class AuthorizationProvider:
    """Optional action- and record-level authorization via keelpolicy.

    Without a provider, the SDK performs no authorization — the app is
    trusted. With a provider, action+subject rules gate every operation,
    and `record.*` conditions are enforced: compiled to SQL for query,
    evaluated per-record for get/update/delete.

    Field-level rules require `enable_field_rules=True`; a policy that
    declares field rules without it fails closed at startup.
    """

    def __init__(self, policy_path: str, enable_field_rules: bool = False) -> None:
        self.statements = load_policy(policy_path)
        self.enable_field_rules = enable_field_rules
        if not enable_field_rules and any(
            "fields" in stmt for stmt in self.statements
        ):
            raise ConfigurationError(
                "policy declares field rules but field-level auth is not enabled"
            )

    def check(self, operation: Operation, resource: str, context: OperationContext) -> None:
        """Action+subject check; `record.*` parts of conditions are deferred
        to `record_allowed` / `record_filter` since no record exists yet."""
        request = PolicyRequest(
            action=operation.value,
            resource=resource,
            subject=context.subject,
            attributes=context.attributes,
        )
        allowed = False
        for stmt in self.statements:
            if not _matches_without_record(stmt, request):
                continue
            if stmt["effect"] == "deny":
                raise PermissionDenied(
                    f"{operation.value} on {resource}: "
                    f"{stmt.get('reason', 'explicit deny')}"
                )
            allowed = True
        if not allowed:
            raise PermissionDenied(f"{operation.value} on {resource}: default deny")

    def record_allowed(
        self,
        operation: Operation,
        resource: str,
        context: OperationContext,
        instance: Any,
    ) -> bool:
        record = {
            col.name: getattr(instance, col.name)
            for col in instance.__table__.columns
        }
        request = PolicyRequest(
            action=operation.value,
            resource=resource,
            subject=context.subject,
            attributes=context.attributes,
            record=record,
        )
        return evaluate(self.statements, request).decision == Decision.ALLOW

    def record_filter(
        self,
        resource: str,
        context: OperationContext,
        model: Any,
        coercer: Any,
    ) -> Any | None:
        """SQL fragment limiting query to authorized records, or None.

        Only `record.*` leaves become SQL; subject/attribute clauses were
        already satisfied by `check`. An allow statement whose condition
        cannot be translated fails closed via ConfigurationError.
        """
        allow_conds, deny_conds = self._conditions(resource, context)
        from sqlalchemy import and_, not_, or_

        parts = []
        if allow_conds:
            compiled = [
                self._compile_condition(cond, model, coercer) for cond in allow_conds
            ]
            parts.append(or_(*compiled) if len(compiled) > 1 else compiled[0])
        for cond in deny_conds:
            parts.append(not_(self._compile_condition(cond, model, coercer)))
        if not parts:
            return None
        return and_(*parts)

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
                    raise PermissionDenied(
                        f"{operation.value} on {resource}: field {field_name!r} denied"
                    )
        return data

    def _conditions(
        self, resource: str, context: OperationContext
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        allows, denies = [], []
        for stmt in self.statements:
            if "condition" not in stmt:
                continue
            request = PolicyRequest(
                action="query",
                resource=resource,
                subject=context.subject,
                attributes=context.attributes,
            )
            if not _matches_without_record(stmt, request):
                continue
            if stmt["effect"] == "allow":
                allows.append(stmt["condition"])
            else:
                denies.append(stmt["condition"])
        return allows, denies

    def _compile_condition(self, condition: dict[str, Any], model: Any, coercer: Any) -> Any:
        from sqlalchemy import and_, or_

        if set(condition) == {"all"}:
            return and_(*[self._compile_condition(c, model, coercer) for c in condition["all"]])
        if set(condition) == {"any"}:
            return or_(*[self._compile_condition(c, model, coercer) for c in condition["any"]])
        if set(condition) == {"field", "op", "value"}:
            field = condition["field"]
            if not str(field).startswith("record."):
                raise ConfigurationError(
                    f"non-record field {field!r} cannot be compiled to SQL"
                )
            name = field[len("record."):]
            if not hasattr(model, name):
                raise ConfigurationError(
                    f"policy record field {name!r} is not a model column"
                )
            column = getattr(model, name)
            value = coercer(name, condition["value"])
            op = condition["op"]
            if op == "eq":
                return column == value
            if op == "ne":
                return column != value
            if op == "in":
                return column.in_([coercer(name, v) for v in value])
            raise ConfigurationError(f"policy operator {op!r} cannot be compiled to SQL")
        raise ConfigurationError(f"unsupported policy condition shape: {sorted(condition)}")


def _matches_without_record(stmt: dict[str, Any], request: PolicyRequest) -> bool:
    actions = stmt["actions"]
    if request.action not in actions and "*" not in actions:
        return False
    for pattern in stmt["resources"]:
        matched = (
            pattern == "*"
            or (pattern.endswith("*") and request.resource.startswith(pattern[:-1]))
            or pattern == request.resource
        )
        if matched:
            break
    else:
        return False
    roles = request.subject.get("roles", ())
    if isinstance(roles, str):
        roles = (roles,)
    for pattern in stmt["subjects"]:
        if pattern == "*" or (pattern.startswith("role:") and pattern[5:] in roles):
            break
    else:
        return False
    return _condition_satisfied_outside_record(stmt.get("condition"), request)


def _condition_satisfied_outside_record(condition: Any, request: PolicyRequest) -> bool:
    if condition is None:
        return True
    if set(condition) == {"all"}:
        return all(_condition_satisfied_outside_record(c, request) for c in condition["all"])
    if set(condition) == {"any"}:
        return any(_condition_satisfied_outside_record(c, request) for c in condition["any"])
    if set(condition) == {"field", "op", "value"}:
        field = condition["field"]
        if str(field).startswith("record."):
            return True  # record parts handled separately
        from keelpolicy.evaluator import _eval_field_op

        return _eval_field_op(condition, request)
    return False
