"""
Three-valued logical evaluator — AND/OR with PASS/FAIL/UNKNOWN.

Implements proper Kleene three-valued logic (§31):

AND truth table:
    PASS ∧ PASS    = PASS
    PASS ∧ UNKNOWN = UNKNOWN
    PASS ∧ FAIL    = FAIL
    UNKNOWN ∧ UNKNOWN = UNKNOWN
    FAIL ∧ anything = FAIL

OR truth table:
    FAIL ∨ FAIL    = FAIL
    PASS ∨ anything = PASS
    FAIL ∨ UNKNOWN = UNKNOWN
    UNKNOWN ∨ UNKNOWN = UNKNOWN
"""

import re
from typing import List, Dict

from app.eligibility.models import RuleStatus, RuleResult

# An OR group is named "OR" or uses OR as a separate name token:
# "OR", "OR_region", "category_or", "or-2". A name that merely contains the
# letters "or" (e.g. "land_for_smallholders", "MAJOR") is NOT an OR group.
_OR_GROUP = re.compile(r"(^|[_\-\s])OR($|[_\-\s0-9])", re.IGNORECASE)


def is_or_group(group_name: str) -> bool:
    """True when a logical_group name denotes an OR group (§29)."""
    return bool(group_name) and bool(_OR_GROUP.search(group_name))


def logical_and(statuses: List[RuleStatus]) -> RuleStatus:
    """
    Evaluate AND across multiple rule statuses (§31).

    FAIL dominates: if any is FAIL → FAIL.
    Then UNKNOWN: if any is UNKNOWN → UNKNOWN.
    Otherwise PASS.
    """
    if not statuses:
        return RuleStatus.PASS  # Vacuously true

    # Filter out NOT_APPLICABLE — they don't affect the decision
    relevant = [s for s in statuses if s != RuleStatus.NOT_APPLICABLE]
    if not relevant:
        return RuleStatus.PASS

    if RuleStatus.FAIL in relevant:
        return RuleStatus.FAIL
    if RuleStatus.UNKNOWN in relevant:
        return RuleStatus.UNKNOWN
    return RuleStatus.PASS


def logical_or(statuses: List[RuleStatus]) -> RuleStatus:
    """
    Evaluate OR across multiple rule statuses (§31).

    PASS dominates: if any is PASS → PASS.
    Then UNKNOWN: if any is UNKNOWN → UNKNOWN.
    Otherwise FAIL.
    """
    if not statuses:
        return RuleStatus.FAIL  # Vacuously false

    relevant = [s for s in statuses if s != RuleStatus.NOT_APPLICABLE]
    if not relevant:
        return RuleStatus.NOT_APPLICABLE

    if RuleStatus.PASS in relevant:
        return RuleStatus.PASS
    if RuleStatus.UNKNOWN in relevant:
        return RuleStatus.UNKNOWN
    return RuleStatus.FAIL


def evaluate_logical_groups(rule_results: List[RuleResult]) -> RuleStatus:
    """
    Evaluate rule results grouped by logical_group (§29–§30).

    Rules within the same logical_group are combined with OR.
    Groups are combined with AND.

    Example:
        Group "AND": rule1=PASS, rule2=PASS → PASS
        Group "category_or": rule3=FAIL, rule4=PASS → PASS (OR)
        Final: PASS AND PASS = PASS
    """
    if not rule_results:
        return RuleStatus.PASS  # No rules = no restrictions (§76, §77)

    # Group results by logical_group
    groups: Dict[str, List[RuleStatus]] = {}
    for r in rule_results:
        group = r.logical_group or "AND"
        groups.setdefault(group, []).append(r.status)

    # Evaluate each group
    group_statuses: List[RuleStatus] = []

    for group_name, statuses in groups.items():
        if is_or_group(group_name):
            # OR group: any can pass (e.g., "OR", "category_or", "OR_region")
            group_statuses.append(logical_or(statuses))
        else:
            # "AND" and any other named group: all must pass
            group_statuses.append(logical_and(statuses))

    # Combine all groups with AND
    return logical_and(group_statuses)
