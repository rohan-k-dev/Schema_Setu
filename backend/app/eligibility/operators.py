"""
Eligibility rule operators — pure deterministic functions.

Each operator takes a normalized user value and a normalized rule value,
returning a RuleStatus. No LLM, DB, Graph, or Web calls allowed (§14, §151).

Three-valued: returns UNKNOWN when user value is None/missing (§26).
"""

from typing import Any, List, Optional

from app.eligibility.models import RuleStatus


def _is_missing(value: Any) -> bool:
    """Check if a value is missing/unknown (§26)."""
    return value is None


def evaluate_eq(user_value: Any, rule_value: Any) -> RuleStatus:
    """EQ: user_value == rule_value (§16)."""
    if _is_missing(user_value):
        return RuleStatus.UNKNOWN
    if _is_missing(rule_value):
        return RuleStatus.NOT_APPLICABLE

    return RuleStatus.PASS if str(user_value) == str(rule_value) else RuleStatus.FAIL


def evaluate_neq(user_value: Any, rule_value: Any) -> RuleStatus:
    """NEQ: user_value != rule_value."""
    if _is_missing(user_value):
        return RuleStatus.UNKNOWN
    if _is_missing(rule_value):
        return RuleStatus.NOT_APPLICABLE

    return RuleStatus.PASS if str(user_value) != str(rule_value) else RuleStatus.FAIL


def evaluate_in(user_value: Any, rule_values: Any) -> RuleStatus:
    """IN: user_value is in the rule's allowed list (§16, §18, §19, §83)."""
    if _is_missing(user_value):
        return RuleStatus.UNKNOWN

    if not isinstance(rule_values, list):
        rule_values = [rule_values]

    if not rule_values:
        return RuleStatus.NOT_APPLICABLE

    user_str = str(user_value).strip().lower()
    for rv in rule_values:
        if rv is not None and str(rv).strip().lower() == user_str:
            return RuleStatus.PASS
    return RuleStatus.FAIL


def evaluate_not_in(user_value: Any, rule_values: Any) -> RuleStatus:
    """NOT_IN: user_value is NOT in the rule's excluded list (§36)."""
    if _is_missing(user_value):
        return RuleStatus.UNKNOWN

    if not isinstance(rule_values, list):
        rule_values = [rule_values]

    if not rule_values:
        return RuleStatus.NOT_APPLICABLE

    user_str = str(user_value).strip().lower()
    for rv in rule_values:
        if rv is not None and str(rv).strip().lower() == user_str:
            return RuleStatus.FAIL
    return RuleStatus.PASS


def evaluate_lt(user_value: Any, rule_value: Any) -> RuleStatus:
    """LT: user_value < rule_value (numeric) (§22)."""
    if _is_missing(user_value):
        return RuleStatus.UNKNOWN
    if _is_missing(rule_value):
        return RuleStatus.NOT_APPLICABLE

    try:
        u = float(user_value)
        r = float(rule_value)
        return RuleStatus.PASS if u < r else RuleStatus.FAIL
    except (ValueError, TypeError):
        return RuleStatus.UNKNOWN  # Can't compare non-numeric safely (§80)


def evaluate_lte(user_value: Any, rule_value: Any) -> RuleStatus:
    """LTE: user_value <= rule_value (numeric) (§22)."""
    if _is_missing(user_value):
        return RuleStatus.UNKNOWN
    if _is_missing(rule_value):
        return RuleStatus.NOT_APPLICABLE

    try:
        u = float(user_value)
        r = float(rule_value)
        return RuleStatus.PASS if u <= r else RuleStatus.FAIL
    except (ValueError, TypeError):
        return RuleStatus.UNKNOWN


def evaluate_gt(user_value: Any, rule_value: Any) -> RuleStatus:
    """GT: user_value > rule_value (numeric)."""
    if _is_missing(user_value):
        return RuleStatus.UNKNOWN
    if _is_missing(rule_value):
        return RuleStatus.NOT_APPLICABLE

    try:
        u = float(user_value)
        r = float(rule_value)
        return RuleStatus.PASS if u > r else RuleStatus.FAIL
    except (ValueError, TypeError):
        return RuleStatus.UNKNOWN


def evaluate_gte(user_value: Any, rule_value: Any) -> RuleStatus:
    """GTE: user_value >= rule_value (numeric)."""
    if _is_missing(user_value):
        return RuleStatus.UNKNOWN
    if _is_missing(rule_value):
        return RuleStatus.NOT_APPLICABLE

    try:
        u = float(user_value)
        r = float(rule_value)
        return RuleStatus.PASS if u >= r else RuleStatus.FAIL
    except (ValueError, TypeError):
        return RuleStatus.UNKNOWN


def evaluate_between(user_value: Any, rule_value: Any) -> RuleStatus:
    """BETWEEN: rule_value[0] <= user_value <= rule_value[1] (§13)."""
    if _is_missing(user_value):
        return RuleStatus.UNKNOWN

    if not isinstance(rule_value, list) or len(rule_value) != 2:
        return RuleStatus.UNKNOWN  # Malformed BETWEEN rule (§80)

    try:
        u = float(user_value)
        low = float(rule_value[0])
        high = float(rule_value[1])
        return RuleStatus.PASS if low <= u <= high else RuleStatus.FAIL
    except (ValueError, TypeError):
        return RuleStatus.UNKNOWN


def evaluate_contains(user_value: Any, rule_value: Any) -> RuleStatus:
    """CONTAINS: rule_value is a substring of user_value."""
    if _is_missing(user_value):
        return RuleStatus.UNKNOWN
    if _is_missing(rule_value):
        return RuleStatus.NOT_APPLICABLE

    u_str = str(user_value).strip().lower()
    r_str = str(rule_value).strip().lower()
    return RuleStatus.PASS if r_str in u_str else RuleStatus.FAIL


def evaluate_boolean(user_value: Any, rule_value: Any) -> RuleStatus:
    """BOOLEAN: user_value matches expected boolean (§21)."""
    if _is_missing(user_value):
        return RuleStatus.UNKNOWN

    # Normalize both to Python bool
    def to_bool(v):
        if isinstance(v, bool):
            return v
        s = str(v).strip().lower()
        if s in ("true", "yes", "1"):
            return True
        if s in ("false", "no", "0"):
            return False
        return None

    u_bool = to_bool(user_value)
    r_bool = to_bool(rule_value)

    if u_bool is None:
        return RuleStatus.UNKNOWN
    if r_bool is None:
        return RuleStatus.NOT_APPLICABLE

    return RuleStatus.PASS if u_bool == r_bool else RuleStatus.FAIL


# ─── Operator dispatch table ─────────────────────────────────

OPERATOR_MAP = {
    "EQ": evaluate_eq,
    "NEQ": evaluate_neq,
    "IN": evaluate_in,
    "NOT_IN": evaluate_not_in,
    "LT": evaluate_lt,
    "LTE": evaluate_lte,
    "GT": evaluate_gt,
    "GTE": evaluate_gte,
    "BETWEEN": evaluate_between,
    "CONTAINS": evaluate_contains,
    "BOOLEAN": evaluate_boolean,
}


def evaluate_operator(operator: str, user_value: Any, rule_value: Any) -> RuleStatus:
    """
    Dispatch to the correct operator function (§12).

    Returns UNKNOWN for unknown operators — never silently passes (§79).
    """
    op_func = OPERATOR_MAP.get(operator.upper())
    if op_func is None:
        return RuleStatus.UNKNOWN  # Unknown operator → UNKNOWN, reported as config error
    return op_func(user_value, rule_value)
