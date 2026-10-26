"""
Rule and profile validators — detect invalid configurations (§79, §186).

Validates rules before evaluation and profile values before comparison.
"""

from typing import List, Dict, Any, Tuple

from app.eligibility.models import RuleOperator
from app.eligibility.normalizer import safe_parse_numeric
from app.core.logging import get_logger

logger = get_logger(__name__)

# All supported operators (§12)
VALID_OPERATORS = {op.value for op in RuleOperator if op != RuleOperator.UNKNOWN}

# Numeric fields requiring float comparison (§22–§25)
NUMERIC_FIELDS = {"land_size_acres", "annual_income", "land", "income", "land_size"}

# Fields requiring numeric operators
NUMERIC_OPERATORS = {"LT", "LTE", "GT", "GTE", "BETWEEN"}


def validate_rule(rule) -> List[Dict[str, str]]:
    """
    Validate a single rule configuration (§79, §80).

    Returns list of issues found. Empty list = valid.
    """
    issues = []

    # Check operator is known
    if rule.operator.upper() not in VALID_OPERATORS:
        issues.append({
            "type": "UNKNOWN_OPERATOR",
            "field": rule.field_name,
            "operator": rule.operator,
            "message": f"Unknown operator '{rule.operator}' for field '{rule.field_name}'",
        })

    # Check numeric fields have parseable values (§80)
    if rule.operator.upper() in NUMERIC_OPERATORS:
        val = rule.value_json
        if isinstance(val, list):
            for v in val:
                if safe_parse_numeric(v) is None:
                    issues.append({
                        "type": "UNPARSEABLE_NUMERIC",
                        "field": rule.field_name,
                        "value": str(v),
                        "message": f"Cannot parse '{v}' as numeric for {rule.operator}",
                    })
        elif val is not None and safe_parse_numeric(val) is None:
            issues.append({
                "type": "UNPARSEABLE_NUMERIC",
                "field": rule.field_name,
                "value": str(val),
                "message": f"Cannot parse '{val}' as numeric for {rule.operator}",
            })

    # Check BETWEEN has exactly 2 values
    if rule.operator.upper() == "BETWEEN":
        if not isinstance(rule.value_json, list) or len(rule.value_json) != 2:
            issues.append({
                "type": "INVALID_BETWEEN",
                "field": rule.field_name,
                "message": f"BETWEEN requires exactly 2 values, got: {rule.value_json}",
            })

    return issues


def validate_rules(rules) -> Tuple[List, List[Dict[str, str]]]:
    """
    Validate all rules. Returns (valid_rules, all_issues).
    """
    all_issues = []
    valid = []

    for rule in rules:
        issues = validate_rule(rule)
        if issues:
            all_issues.extend(issues)
            logger.warning(f"Rule validation issues: {issues}")
        valid.append(rule)  # Still include — evaluator handles gracefully

    return valid, all_issues


def validate_profile_value(field: str, value: Any) -> Tuple[bool, str]:
    """
    Validate a profile value is reasonable (§184–§186).

    Returns (is_valid, error_message).
    """
    if value is None:
        return True, ""  # None is valid (means unknown)

    # Numeric field validation
    if field in NUMERIC_FIELDS:
        parsed = safe_parse_numeric(value)
        if parsed is not None and parsed < 0:
            return False, f"Negative value for {field}: {value}"
        # "a lot" etc. are treated as unknown, not invalid
        return True, ""

    return True, ""


def generate_rule_quality_report(rules) -> Dict[str, Any]:
    """
    Generate a quality report for a set of rules (§173).
    """
    total = len(rules)
    by_field = {}
    by_operator = {}
    with_source = 0
    invalid = 0
    invalid_details = []

    for rule in rules:
        # Count by field
        field = rule.field_name
        by_field[field] = by_field.get(field, 0) + 1

        # Count by operator
        op = rule.operator.upper()
        by_operator[op] = by_operator.get(op, 0) + 1

        # Source text
        if rule.source_text:
            with_source += 1

        # Validation
        issues = validate_rule(rule)
        if issues:
            invalid += 1
            invalid_details.extend(issues)

    return {
        "total_rules": total,
        "rules_by_field": by_field,
        "rules_by_operator": by_operator,
        "rules_with_source_text": with_source,
        "invalid_rules": invalid,
        "invalid_details": invalid_details,
    }
