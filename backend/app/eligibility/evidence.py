"""
Evidence builder — transforms RuleResult[] into structured evidence (§46).

Categorizes rule results into matched, failed, missing, and conflict
categories for XAI consumption.
"""

from typing import List, Dict, Any

from app.eligibility.models import (
    RuleStatus, RuleResult, EligibilityResult,
    ExplanationItem, ExplanationType,
)


def build_evidence(result: EligibilityResult) -> Dict[str, Any]:
    """
    Transform an EligibilityResult into structured evidence (§46).

    Returns:
        matched_criteria, failed_criteria, missing_criteria,
        exclusions, source_references
    """
    matched = []
    failed = []
    missing = []
    exclusions = []

    for r in result.rule_results:
        item = {
            "field": r.field,
            "operator": r.operator,
            "user_value": r.user_value,
            "required_value": r.required_value,
            "source_text": r.source_text,
            "unit": r.unit,
            "explanation_key": r.explanation_key,
        }

        if r.status == RuleStatus.PASS:
            matched.append(item)
        elif r.status == RuleStatus.FAIL:
            if r.operator in ("NOT_IN",):
                exclusions.append(item)
            else:
                failed.append(item)
        elif r.status == RuleStatus.UNKNOWN:
            missing.append(item)

    return {
        "matched_criteria": matched,
        "failed_criteria": failed,
        "missing_criteria": missing,
        "exclusions": exclusions,
        "source_references": result.source_references,
        "conflicts": result.conflicts,
    }


def build_explanation_items(result: EligibilityResult) -> List[ExplanationItem]:
    """
    Build typed ExplanationItem list from an EligibilityResult (§190).
    """
    items = []

    for r in result.rule_results:
        if r.status == RuleStatus.PASS:
            items.append(ExplanationItem(
                type=ExplanationType.MATCHED,
                field=r.field,
                status=r.status,
                user_value=r.user_value,
                required_value=r.required_value,
                text_key=r.explanation_key,
                source=r.source_text,
            ))
        elif r.status == RuleStatus.FAIL:
            items.append(ExplanationItem(
                type=ExplanationType.FAILED,
                field=r.field,
                status=r.status,
                user_value=r.user_value,
                required_value=r.required_value,
                text_key=r.explanation_key,
                source=r.source_text,
            ))
        elif r.status == RuleStatus.UNKNOWN:
            items.append(ExplanationItem(
                type=ExplanationType.MISSING,
                field=r.field,
                status=r.status,
                user_value=None,
                required_value=r.required_value,
                text_key=r.explanation_key,
                source=r.source_text,
            ))

    # Add conflict items
    for conflict in result.conflicts:
        items.append(ExplanationItem(
            type=ExplanationType.CONFLICT,
            field=conflict.get("field", "unknown"),
            status=RuleStatus.UNKNOWN,
            text_key="RULE_CONFLICT",
            source=conflict.get("message"),
        ))

    return items
