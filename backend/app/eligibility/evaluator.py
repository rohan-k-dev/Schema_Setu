"""
Eligibility evaluator — deterministic rule evaluation engine.

Evaluates structured eligibility rules against a farmer profile.
No LLM, no DB, no Graph, no Web calls (§14, §151–§152).

Key design:
- Complete evaluation: evaluates ALL rules even after first FAIL (§70)
- Three-valued: PASS/FAIL/UNKNOWN — never treats missing as FAIL (§26)
- Conflict detection: identifies contradictory rules (§37)
- Schemes without rules → UNVERIFIABLE (§174)
"""

import time
from typing import List, Dict, Any, Optional, Tuple

from app.eligibility.models import (
    RuleStatus, EligibilityStatus, RuleResult,
    EligibilityResult, RuleOperator, ELIGIBILITY_ENGINE_VERSION,
)
from app.eligibility.operators import evaluate_operator, OPERATOR_MAP
from app.eligibility.logical import evaluate_logical_groups, is_or_group
from app.eligibility.normalizer import normalize_field_value, normalize_rule_value
from app.core.logging import get_logger

logger = get_logger(__name__)

# Profile field name mapping (§78): DB rule field names → profile field names
FIELD_NAME_MAP = {
    "land": "land_size_acres",
    "land_size": "land_size_acres",
    "income": "annual_income",
    "crop": "primary_crop",
    "caste": "category",
    "social_category": "category",
    "aadhaar": "has_aadhaar",
}


def _resolve_field_name(rule_field: str) -> str:
    """Map rule field name to canonical profile field name (§78)."""
    return FIELD_NAME_MAP.get(rule_field.lower(), rule_field.lower())


def _get_profile_value(profile: Dict[str, Any], field: str) -> Any:
    """Get a profile value, resolving field name aliases and documented derivations."""
    canonical = _resolve_field_name(field)
    # Try canonical name first, then original
    val = profile.get(canonical)
    if val is None:
        val = profile.get(field)
    if val is None and canonical == "has_land":
        val = _derive_has_land(profile)
    return val


def _derive_has_land(profile: Dict[str, Any]) -> Optional[bool]:
    """
    Derived-field policy: a user who states a land holding of X acres has
    land when X > 0 and has none when X == 0. Unknown/invalid land stays
    unknown. An explicit has_land value always takes precedence.
    """
    acres = normalize_field_value("land_size_acres", profile.get("land_size_acres"))
    if acres is None:
        return None
    return acres > 0


def evaluate_rule(rule, profile: Dict[str, Any], source_url: Optional[str] = None) -> RuleResult:
    """
    Evaluate a single eligibility rule against a profile (§13).

    Pure function: uses only rule definition + profile value.
    Returns UNKNOWN when profile value is missing (§26).
    """
    field_name = rule.field_name
    operator = rule.operator.upper()
    rule_value = rule.value_json
    canonical_field = _resolve_field_name(field_name)

    # Get user value from profile
    raw_user_value = _get_profile_value(profile, field_name)

    # Normalize both values (§15)
    user_value = normalize_field_value(canonical_field, raw_user_value)
    normalized_rule_value = normalize_rule_value(canonical_field, rule_value)

    # Check for unknown operator (§79)
    if operator not in OPERATOR_MAP and operator != "UNKNOWN":
        return RuleResult(
            rule_id=rule.rule_id,
            field=canonical_field,
            operator=operator,
            user_value=raw_user_value,
            required_value=rule_value,
            status=RuleStatus.UNKNOWN,
            source_text=rule.source_text,
            source_url=source_url,
            explanation_key="UNKNOWN_OPERATOR",
            logical_group=rule.logical_group or "AND",
            required=rule.required,
            unit=rule.unit,
        )

    # Evaluate the operator
    status = evaluate_operator(operator, user_value, normalized_rule_value)

    # Determine explanation key (§191)
    explanation_key = _get_explanation_key(canonical_field, operator, status)

    return RuleResult(
        rule_id=rule.rule_id,
        field=canonical_field,
        operator=operator,
        user_value=user_value if user_value is not None else raw_user_value,
        required_value=rule_value,
        status=status,
        source_text=rule.source_text,
        source_url=source_url,
        explanation_key=explanation_key,
        logical_group=rule.logical_group or "AND",
        required=rule.required,
        unit=rule.unit,
    )


def _get_explanation_key(field: str, operator: str, status: RuleStatus) -> str:
    """Generate a structured explanation key (§191)."""
    field_upper = field.upper()
    status_lower = status.value.lower()

    key_map = {
        ("land_size_acres", "LTE", "PASS"): "LAND_WITHIN_LIMIT",
        ("land_size_acres", "LTE", "FAIL"): "LAND_EXCEEDS_LIMIT",
        ("annual_income", "LTE", "PASS"): "INCOME_WITHIN_LIMIT",
        ("annual_income", "LTE", "FAIL"): "INCOME_EXCEEDS_LIMIT",
    }

    specific = key_map.get((field, operator, status.value))
    if specific:
        return specific

    return f"{field_upper}_{operator}_{status_lower}".upper()


def _detect_rule_conflicts(rules) -> List[Dict[str, Any]]:
    """
    Detect contradictory rules for the same field (§37).

    Example: land <= 5 AND land >= 10 → conflict.
    """
    conflicts = []
    field_rules: Dict[str, List] = {}

    for r in rules:
        canonical = _resolve_field_name(r.field_name)
        field_rules.setdefault(canonical, []).append(r)

    for field, field_rule_list in field_rules.items():
        if len(field_rule_list) < 2:
            continue

        # Check for numeric contradictions
        upper_bounds = []
        lower_bounds = []
        for r in field_rule_list:
            op = r.operator.upper()
            val = r.value_json
            if op in ("LTE", "LT") and val is not None:
                try:
                    upper_bounds.append(float(val))
                except (ValueError, TypeError):
                    pass
            elif op in ("GTE", "GT") and val is not None:
                try:
                    lower_bounds.append(float(val))
                except (ValueError, TypeError):
                    pass

        # Categorical contradictions: required AND-combined EQ/IN rules on the
        # same field whose allowed values do not overlap can never all pass,
        # e.g. state IN [karnataka] AND state IN [maharashtra] (§38).
        allowed_sets = []
        for r in field_rule_list:
            if r.operator.upper() not in ("EQ", "IN") or not getattr(r, "required", True):
                continue
            if is_or_group(r.logical_group or "AND"):
                continue
            values = r.value_json if isinstance(r.value_json, list) else [r.value_json]
            normalized = {str(v) for v in normalize_rule_value(field, values) if v is not None}
            if normalized:
                allowed_sets.append(normalized)
        if len(allowed_sets) >= 2 and not set.intersection(*allowed_sets):
            conflicts.append({
                "field": field,
                "type": "CONTRADICTORY_VALUES",
                "message": f"{field}: required rules allow disjoint values {[sorted(a) for a in allowed_sets]}",
            })

        if upper_bounds and lower_bounds:
            max_upper = max(upper_bounds)
            min_lower = min(lower_bounds)
            if min_lower > max_upper:
                conflicts.append({
                    "field": field,
                    "type": "CONTRADICTORY_BOUNDS",
                    "upper_bound": max_upper,
                    "lower_bound": min_lower,
                    "message": f"{field}: upper bound {max_upper} < lower bound {min_lower}",
                })

    return conflicts


def evaluate_scheme(
    scheme_id: str,
    scheme_name: str,
    rules,
    profile: Dict[str, Any],
    corpus_version: str = "1.0.0",
    source_url: Optional[str] = None,
) -> EligibilityResult:
    """
    Evaluate all rules for a single scheme (§43).

    Complete evaluation: evaluates ALL rules, even after first FAIL (§70).
    source_url: the scheme's official source, attached to every RuleResult
    for provenance (§39). Never invented — None when the corpus has none.
    """
    start = time.time()

    # No rules → UNVERIFIABLE (§174)
    if not rules:
        logger.info(f"Scheme {scheme_id}: no structured rules → UNVERIFIABLE")
        return EligibilityResult(
            scheme_id=scheme_id,
            scheme_name=scheme_name,
            status=EligibilityStatus.UNVERIFIABLE,
            needs_review=True,
            corpus_version=corpus_version,
        )

    # Detect rule conflicts (§37)
    conflicts = _detect_rule_conflicts(rules)

    # Evaluate all rules (§70: complete evaluation)
    rule_results: List[RuleResult] = []
    for rule in rules:
        result = evaluate_rule(rule, profile, source_url=source_url)
        rule_results.append(result)

    # Count statuses
    passed = sum(1 for r in rule_results if r.status == RuleStatus.PASS)
    failed = sum(1 for r in rule_results if r.status == RuleStatus.FAIL)
    unknown = sum(1 for r in rule_results if r.status == RuleStatus.UNKNOWN)
    na = sum(1 for r in rule_results if r.status == RuleStatus.NOT_APPLICABLE)

    # Identify missing information (§27)
    missing_info = [
        r.field for r in rule_results
        if r.status == RuleStatus.UNKNOWN and r.required
    ]

    # Collect source references
    sources = []
    for r in rule_results:
        if r.source_text:
            ref = {"text": r.source_text, "field": r.field}
            if r.source_url:
                ref["url"] = r.source_url
            sources.append(ref)

    # Determine final status (§33)
    if conflicts:
        final_status = EligibilityStatus.UNVERIFIABLE
    else:
        # Use logical group evaluation (§29)
        # Only consider required rules for the final decision
        required_results = [r for r in rule_results if r.required]
        if not required_results:
            # Only optional rules → eligible by default
            final_status = EligibilityStatus.ELIGIBLE
        else:
            logical_result = evaluate_logical_groups(required_results)

            if logical_result == RuleStatus.PASS:
                final_status = EligibilityStatus.ELIGIBLE
            elif logical_result == RuleStatus.FAIL:
                final_status = EligibilityStatus.NOT_ELIGIBLE
            elif logical_result == RuleStatus.UNKNOWN:
                final_status = EligibilityStatus.NEEDS_MORE_INFORMATION
            else:
                final_status = EligibilityStatus.UNVERIFIABLE

    elapsed_ms = (time.time() - start) * 1000
    logger.info(
        f"Scheme {scheme_id}: {final_status.value} "
        f"(P={passed} F={failed} U={unknown} NA={na}) in {elapsed_ms:.1f}ms"
    )

    return EligibilityResult(
        scheme_id=scheme_id,
        scheme_name=scheme_name,
        status=final_status,
        rule_results=rule_results,
        passed_rules=passed,
        failed_rules=failed,
        unknown_rules=unknown,
        not_applicable_rules=na,
        missing_information=missing_info,
        conflicts=conflicts,
        source_references=sources,
        corpus_version=corpus_version,
        needs_review=bool(conflicts),
    )


def evaluate_candidates(
    candidates: List[Dict[str, Any]],
    rules_by_scheme: Dict[str, list],
    profile: Dict[str, Any],
    corpus_version: str = "1.0.0",
) -> List[EligibilityResult]:
    """
    Batch evaluate all candidate schemes (§43).

    candidates: list of merged candidate dicts
    rules_by_scheme: {scheme_id: [EligibilityRuleRow, ...]}
    profile: user profile dict
    """
    results = []

    for candidate in candidates:
        scheme_id = candidate.get("scheme_id", "")
        scheme_name = candidate.get("name", "")
        rules = rules_by_scheme.get(scheme_id, [])

        result = evaluate_scheme(
            scheme_id=scheme_id,
            scheme_name=scheme_name,
            rules=rules,
            profile=profile,
            corpus_version=corpus_version,
            source_url=candidate.get("official_url"),
        )
        results.append(result)

    return results
