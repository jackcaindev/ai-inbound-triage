from typing import Any, Literal

from pydantic import BaseModel

ConditionOp = Literal[
    "eq", "gt", "gte", "lt", "lte", "contains", "any_gte", "any_gt", "any_lte", "any_lt"
]


class Condition(BaseModel):
    """One clause in a rule's condition list. A list of conditions on a Rule is ANDed
    together — first rule (by priority) whose conditions all match wins.

    Either `category` is set (an equality check against the classified category), or
    `field`/`op`/`value` are set (a comparison against an extracted field). The
    `any_*` ops treat the field as a list and match if any element satisfies the
    comparison — e.g. {"field": "dollar_amounts_mentioned", "op": "any_gte", "value": 10000}.
    """

    category: str | None = None
    field: str | None = None
    op: ConditionOp | None = None
    value: Any = None


def condition_matches(condition: Condition, category: str, fields: dict[str, Any]) -> bool:
    if condition.category is not None:
        return category == condition.category

    if condition.field is None or condition.op is None:
        return False

    actual = fields.get(condition.field)
    op = condition.op
    target = condition.value

    if op.startswith("any_"):
        if not isinstance(actual, list):
            return False
        scalar_op = op.removeprefix("any_")
        return any(_compare(scalar_op, item, target) for item in actual)

    return _compare(op, actual, target)


def _compare(op: str, actual: Any, target: Any) -> bool:
    if actual is None:
        return False
    if op == "eq":
        return actual == target
    if op == "gt":
        return actual > target
    if op == "gte":
        return actual >= target
    if op == "lt":
        return actual < target
    if op == "lte":
        return actual <= target
    if op == "contains":
        return target in actual
    raise ValueError(f"Unknown condition op: {op}")
