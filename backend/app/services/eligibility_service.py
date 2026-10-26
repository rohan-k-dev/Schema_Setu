"""
Eligibility service — orchestrates rule loading and evaluation (§42, §129).

Responsibilities:
- Load rules from RuleRepository
- Evaluate scheme eligibility
- Return typed results with evidence
- Identify missing information

Does NOT:
- Run SQL directly (uses repository layer)
- Call Tavily/Groq/Sarvam
- Manipulate NetworkX
"""

from typing import List, Dict, Any, Optional

from app.eligibility.models import (
    EligibilityResult, EligibilityStatus, ELIGIBILITY_ENGINE_VERSION,
)
from app.eligibility.evaluator import evaluate_scheme, evaluate_candidates
from app.eligibility.validators import validate_rules, generate_rule_quality_report
from app.xai.explainer import explain
from app.recommendation.ranker import rank_results
from app.recommendation.models import RankedScheme
from app.core.logging import get_logger

logger = get_logger(__name__)


async def evaluate_scheme_eligibility(
    scheme_id: str,
    scheme_name: str,
    rules,
    profile: Dict[str, Any],
    corpus_version: str = "1.0.0",
) -> EligibilityResult:
    """
    Evaluate a single scheme's eligibility (§129).

    Args:
        scheme_id: Canonical scheme identifier
        scheme_name: Human-readable name
        rules: List of EligibilityRuleRow from database
        profile: User profile dict

    Returns:
        EligibilityResult with evidence
    """
    # Validate rules (§79)
    valid_rules, issues = validate_rules(rules)
    if issues:
        logger.warning(
            f"Scheme {scheme_id}: {len(issues)} rule validation issues"
        )

    # Evaluate
    result = evaluate_scheme(
        scheme_id=scheme_id,
        scheme_name=scheme_name,
        rules=valid_rules,
        profile=profile,
        corpus_version=corpus_version,
    )

    # Generate explanation
    explanation = explain(result)
    result.evidence_summary = explanation.summary

    return result


async def evaluate_candidate_schemes(
    candidates: List[Dict[str, Any]],
    rules_by_scheme: Dict[str, list],
    profile: Dict[str, Any],
    graph_evidence: Optional[Dict[str, Any]] = None,
    corpus_version: str = "1.0.0",
) -> List[RankedScheme]:
    """
    Evaluate and rank all candidate schemes (§43, §157).

    1. Batch evaluate all candidates
    2. Build evidence
    3. Rank results
    4. Return ordered list

    Args:
        candidates: List of merged candidate dicts from Phase 4
        rules_by_scheme: Pre-loaded rules {scheme_id: [rules]}
        profile: User profile dict
        graph_evidence: Optional graph match data

    Returns:
        List of RankedScheme ordered by eligibility priority
    """
    if not candidates:
        logger.info("No candidates to evaluate")
        return []

    # Batch evaluate (§43)
    results = evaluate_candidates(
        candidates=candidates,
        rules_by_scheme=rules_by_scheme,
        profile=profile,
        corpus_version=corpus_version,
    )

    # Add evidence summaries
    for result in results:
        explanation = explain(result)
        result.evidence_summary = explanation.summary

    # Rank (§59)
    ranked = rank_results(results, graph_evidence=graph_evidence)

    logger.info(
        f"Evaluated {len(candidates)} candidates → "
        f"{sum(1 for r in results if r.status == EligibilityStatus.ELIGIBLE)} eligible, "
        f"{sum(1 for r in results if r.status == EligibilityStatus.NEEDS_MORE_INFORMATION)} needs info, "
        f"{sum(1 for r in results if r.status == EligibilityStatus.NOT_ELIGIBLE)} not eligible, "
        f"{sum(1 for r in results if r.status == EligibilityStatus.UNVERIFIABLE)} unverifiable"
    )

    return ranked


def get_missing_eligibility_fields(
    results: List[EligibilityResult],
) -> List[str]:
    """
    Extract unique missing fields across all evaluations (§66).

    Returns fields that, if provided, could change NEEDS_MORE_INFORMATION
    to ELIGIBLE or NOT_ELIGIBLE.
    """
    missing = set()
    for result in results:
        if result.status == EligibilityStatus.NEEDS_MORE_INFORMATION:
            missing.update(result.missing_information)
    return sorted(missing)
