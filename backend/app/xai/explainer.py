"""
XAI Explainer — evidence-based explanation engine (§48).

Generates structured explanations from eligibility evidence.
Uses deterministic templates with optional LLM natural-language layer.

The LLM is NEVER the source of eligibility decisions (§4, §56).
It may only simplify/explain evidence that already exists.
"""

from typing import Optional, Dict, Any, List

from app.eligibility.models import (
    EligibilityResult, EligibilityExplanation,
    ExplanationItem, ExplanationType, RuleStatus,
    EligibilityStatus,
)
from app.eligibility.evidence import build_evidence, build_explanation_items
from app.xai.templates import (
    generate_summary, generate_template_explanation,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


def explain(result: EligibilityResult) -> EligibilityExplanation:
    """
    Generate a structured explanation from an EligibilityResult (§48).

    Always deterministic. No LLM calls.
    """
    evidence = build_evidence(result)
    items = build_explanation_items(result)

    summary = generate_summary(result.status)

    matched = [i for i in items if i.type == ExplanationType.MATCHED]
    failed = [i for i in items if i.type == ExplanationType.FAILED]
    missing = [i for i in items if i.type == ExplanationType.MISSING]

    cautions = []
    if result.conflicts:
        cautions.append(
            "Some eligibility criteria contain conflicting information. "
            "Results may not be fully reliable."
        )
    if result.needs_review:
        cautions.append("This evaluation may need manual review.")

    # Collect unique sources
    sources = []
    seen_sources = set()
    for r in result.rule_results:
        if r.source_text and r.source_text not in seen_sources:
            seen_sources.add(r.source_text)
            entry = {"text": r.source_text, "field": r.field}
            if r.source_url:
                entry["url"] = r.source_url
            sources.append(entry)

    return EligibilityExplanation(
        summary=summary,
        matched_criteria=matched,
        failed_criteria=failed,
        missing_criteria=missing,
        cautions=cautions,
        sources=sources,
    )


def explain_for_response(result: EligibilityResult) -> str:
    """
    Generate a natural-language explanation string for the response formatter (§58).

    Uses deterministic templates — no LLM required.
    """
    evidence = build_evidence(result)

    return generate_template_explanation(
        status=result.status,
        matched=evidence["matched_criteria"],
        failed=evidence["failed_criteria"],
        missing=evidence["missing_criteria"],
        scheme_name=result.scheme_name,
    )


def validate_explanation(
    explanation: str,
    result: EligibilityResult,
) -> bool:
    """
    Validate that an explanation is consistent with evidence (§57, §102–§104).

    Rejects an explanation that:
    - claims eligibility when the engine status is not ELIGIBLE (any sentence)
    - claims ineligibility when the engine status is ELIGIBLE
    - contains a number not present in the rule evidence (user/required values, source text)
    - contains a URL not present in the rule evidence
    - states a criterion ("<Field label>: ...") for a field that was never evaluated
    """
    from app.xai.grounding import (
        sentences, affirms_eligibility, NOT_ELIGIBLE_RE, numbers_in, urls_in, numbers_from_values,
    )
    from app.xai.templates import FIELD_LABELS

    status = result.status

    # 1. Status integrity (§46, §119)
    if status != EligibilityStatus.ELIGIBLE and any(affirms_eligibility(s) for s in sentences(explanation)):
        logger.warning(f"Explanation claims eligibility but engine says {status.value}")
        return False
    if status == EligibilityStatus.ELIGIBLE and (
            NOT_ELIGIBLE_RE.search(explanation) or "does not match" in explanation.lower()):
        logger.warning("Explanation claims not eligible but engine says ELIGIBLE")
        return False

    # 2. Numeric grounding (§44, §104)
    evidence_numbers = numbers_from_values(
        [r.user_value for r in result.rule_results]
        + [r.required_value for r in result.rule_results]
        + [r.source_text for r in result.rule_results]
    )
    stray = numbers_in(explanation) - evidence_numbers
    if stray:
        logger.warning(f"Explanation contains numbers without evidence: {sorted(stray)}")
        return False

    # 3. URL grounding (§45, §103)
    evidence_urls = {r.source_url for r in result.rule_results if r.source_url}
    if urls_in(explanation) - evidence_urls:
        logger.warning("Explanation contains a URL that is not in the evidence")
        return False

    # 4. Criteria grounding (§43): "Label:" lines only for evaluated fields
    evaluated = {r.field for r in result.rule_results}
    for field, label in FIELD_LABELS.items():
        if field not in evaluated and f"{label.lower()}:" in explanation.lower():
            logger.warning(f"Explanation states a criterion for unevaluated field '{field}'")
            return False

    return True
