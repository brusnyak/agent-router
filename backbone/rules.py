"""Query operators ported from third_party/portkey-conditional/conditionalRouter.ts."""
import re
from typing import Any


def _get(ctx: Any, key: str) -> Any:
    cur: Any = ctx
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _eval_op(value: Any, op: dict) -> bool:
    for name, compare in op.items():
        if name == "$eq":
            if value != compare:
                return False
        elif name == "$ne":
            if value == compare:
                return False
        elif name in ("$gt", "$gte", "$lt", "$lte"):
            try:
                v, c = float(value), float(compare)
            except (TypeError, ValueError):
                return False
            cmp = {">": v > c, ">=": v >= c, "<": v < c, "<=": v <= c}[
                {"$gt": ">", "$gte": ">=", "$lt": "<", "$lte": "<="}[name]
            ]
            if not cmp:
                return False
        elif name == "$in":
            if not isinstance(compare, list) or value not in compare:
                return False
        elif name == "$nin":
            if not isinstance(compare, list) or value in compare:
                return False
        elif name == "$regex":
            if not isinstance(value, str) or re.search(compare, value) is None:
                return False
        else:
            raise ValueError(f"Unsupported operator: {name}")
    return True


def match(query: dict, ctx: dict) -> bool:
    for key, value in query.items():
        if key == "$or":
            return isinstance(value, list) and any(match(sub, ctx) for sub in value)
        if key == "$and":
            return isinstance(value, list) and all(match(sub, ctx) for sub in value)
        ctx_value = _get(ctx, key)
        if isinstance(value, dict):
            if not _eval_op(ctx_value, value):
                return False
        elif ctx_value != value:
            return False
    return True


def resolve(rules: list[dict], ctx: dict) -> dict | None:
    for rule in rules:
        if match(rule.get("when", {}), ctx):
            return rule
    return None
